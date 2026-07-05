// WebSocket client to the backend /ws/bridge. Routes inbound requests (observe/act/navigate/tabs)
// to the handlers and replies with a `result`/`error` envelope echoing the request id. Sends a
// heartbeat to keep the MV3 service worker alive, and reconnects on drop.
import { PROTOCOL_VERSION } from "@browser-agent/contracts";

import { HEARTBEAT_MS, RECONNECT_MS } from "./config";

export interface BridgeHandlers {
  observe(payload: any): Promise<any>;
  act(payload: any): Promise<any>;
  navigate(payload: any): Promise<any>;
  tabs(payload: any): Promise<any>;
}

/**
 * Turn one inbound message into its reply envelope. Pure and side-effect free (aside from invoking a
 * handler), so it's unit-tested directly. Returns null for anything that isn't a request we handle.
 */
export async function handleRequest(msg: any, handlers: BridgeHandlers): Promise<any | null> {
  if (!msg || typeof msg.type !== "string") return null;
  const fn = (handlers as any)[msg.type];
  if (typeof fn !== "function") return null;
  try {
    const result = await fn(msg.payload ?? {});
    return { protocolVersion: PROTOCOL_VERSION, type: "result", id: msg.id, payload: result };
  } catch (e: any) {
    return {
      protocolVersion: PROTOCOL_VERSION,
      type: "error",
      id: msg.id,
      payload: { message: String(e?.message ?? e), errorCode: "EXT_ERROR" },
    };
  }
}

export class BridgeClient {
  private ws: WebSocket | null = null;
  private heartbeat: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private closed = false;

  constructor(
    private url: string,
    private handlers: BridgeHandlers,
    private register: object,
    private onStatus?: (connected: boolean) => void
  ) {}

  connect(): void {
    this.closed = false;
    const ws = new WebSocket(this.url);
    this.ws = ws;

    ws.onopen = () => {
      this.onStatus?.(true);
      this.rawSend({ protocolVersion: PROTOCOL_VERSION, type: "register", payload: this.register });
      this.heartbeat = setInterval(() => {
        this.rawSend({ protocolVersion: PROTOCOL_VERSION, type: "ping", payload: {} });
      }, HEARTBEAT_MS);
    };

    ws.onmessage = async (evt: MessageEvent) => {
      let msg: any;
      try {
        msg = JSON.parse(typeof evt.data === "string" ? evt.data : "");
      } catch {
        return;
      }
      const reply = await handleRequest(msg, this.handlers);
      if (reply) this.rawSend(reply);
    };

    ws.onclose = () => {
      this.onStatus?.(false);
      this.stopHeartbeat();
      if (!this.closed) this.scheduleReconnect();
    };

    ws.onerror = () => {
      try {
        ws.close();
      } catch {
        /* already closing */
      }
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.closed) this.connect();
    }, RECONNECT_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeat) {
      clearInterval(this.heartbeat);
      this.heartbeat = null;
    }
  }

  private rawSend(env: object): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(env));
    }
  }

  /** A live-view JPEG frame (unsolicited, no id). */
  sendFrame(data: string, meta: Record<string, any>): void {
    this.rawSend({ protocolVersion: PROTOCOL_VERSION, type: "frame", payload: { data, ...meta } });
  }

  close(): void {
    this.closed = true;
    this.stopHeartbeat();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        /* ignore */
      }
      this.ws = null;
    }
  }
}
