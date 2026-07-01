import { useCallback, useEffect, useRef, useState } from "react";
import type { AgentEvent, RunStatus, TimelineItem } from "./types";

export interface Question {
  question: string;
  context?: string;
}

export interface RunResult {
  success: boolean;
  reason: string;
  stopped?: boolean;
}

export interface AgentRunState {
  status: RunStatus;
  task: string;
  timeline: TimelineItem[];
  streaming: string;
  question: Question | null;
  result: RunResult | null;
  error: string | null;
  /** True while a sleeping backend is being woken and the connection retried. */
  waking: boolean;
  hasFrame: boolean;
  pageUrl: string | null;
  /** Subscribe to raw base64 JPEG frames. Frames are pushed imperatively (not via React state)
   *  so a high-FPS stream never re-renders the tree — the Viewport paints them to a canvas. */
  subscribeFrame: (cb: (b64: string) => void) => () => void;
  start: (task: string) => void;
  answer: (text: string) => void;
  stop: () => void;
}

const WS_URL = (import.meta.env.VITE_WS_URL as string | undefined) ?? "ws://localhost:8000/ws/run";
const BUSY: RunStatus[] = ["running", "waiting_for_user", "stopping"];

// Wake a sleeping backend: free hosts like Hugging Face Spaces put idle apps to sleep, and a raw
// WebSocket connect just fails against a sleeping Space. Hitting the HTTP /health endpoint nudges
// the host to boot the container; we retry the socket while it comes up. Derived from WS_URL
// (wss://host/ws/run -> https://host/health).
const WAKE_URL = WS_URL.replace(/^ws/, "http").replace(/\/ws\/run$/, "/health");
const MAX_WAKE_ATTEMPTS = 15; // ~90s of retrying while a cold Space boots
const WAKE_RETRY_MS = 6000;

export function useAgentRun(): AgentRunState {
  const [status, setStatus] = useState<RunStatus>("idle");
  const [task, setTask] = useState<string>("");
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [streaming, setStreaming] = useState<string>("");
  const [question, setQuestion] = useState<Question | null>(null);
  const [result, setResult] = useState<RunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [waking, setWaking] = useState<boolean>(false);
  const [hasFrame, setHasFrame] = useState<boolean>(false);
  const [pageUrl, setPageUrl] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const streamingRef = useRef<string>("");
  const frameCbRef = useRef<((b64: string) => void) | null>(null);
  const hasFrameRef = useRef<boolean>(false);
  const pageUrlRef = useRef<string | null>(null);
  const attemptRef = useRef<number>(0);
  const retryTimerRef = useRef<number | null>(null);

  const clearRetry = useCallback(() => {
    if (retryTimerRef.current !== null) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
  }, []);

  const subscribeFrame = useCallback((cb: (b64: string) => void) => {
    frameCbRef.current = cb;
    return () => {
      if (frameCbRef.current === cb) frameCbRef.current = null;
    };
  }, []);

  const closeSocket = useCallback(() => {
    clearRetry();
    if (wsRef.current) {
      wsRef.current.onopen = null;
      wsRef.current.onmessage = null;
      wsRef.current.onerror = null;
      wsRef.current.onclose = null;
      wsRef.current.close();
      wsRef.current = null;
    }
  }, [clearRetry]);

  const send = useCallback((payload: object) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(payload));
    }
  }, []);

  const flushStreaming = useCallback(() => {
    if (streamingRef.current.trim()) {
      const text = streamingRef.current;
      setTimeline((prev) => [...prev, { kind: "thought", text }]);
    }
    streamingRef.current = "";
    setStreaming("");
  }, []);

  const start = useCallback(
    (taskText: string) => {
      closeSocket();
      attemptRef.current = 0;
      setStatus("running");
      setWaking(false);
      setTask(taskText);
      setTimeline([]);
      setStreaming("");
      streamingRef.current = "";
      setQuestion(null);
      setResult(null);
      setError(null);
      setHasFrame(false);
      hasFrameRef.current = false;
      setPageUrl(null);
      pageUrlRef.current = null;

      const openSocket = () => {
        const ws = new WebSocket(WS_URL);
        wsRef.current = ws;
        let opened = false;
        let settled = false; // schedule at most one retry per attempt (error + close can both fire)

        const onFail = () => {
          if (opened || settled) return;
          settled = true;
          scheduleRetry();
        };

        ws.onopen = () => {
          opened = true;
          attemptRef.current = 0;
          setWaking(false);
          ws.send(JSON.stringify({ type: "start", task: taskText }));
        };

        ws.onmessage = (evt: MessageEvent<string>) => {
          let parsed: AgentEvent;
          try {
            parsed = JSON.parse(evt.data) as AgentEvent;
          } catch {
            return;
          }
          const { event, data } = parsed;

          if (event === "frame") {
            const b64 = data.data as string | undefined;
            if (b64) {
              frameCbRef.current?.(b64);
              if (!hasFrameRef.current) {
                hasFrameRef.current = true;
                setHasFrame(true);
              }
            }
            const url = data.url;
            if (typeof url === "string" && url !== pageUrlRef.current) {
              pageUrlRef.current = url;
              setPageUrl(url);
            }
          } else if (event === "observation") {
            const url = data.url;
            if (typeof url === "string" && url !== pageUrlRef.current) {
              pageUrlRef.current = url;
              setPageUrl(url);
            }
          } else if (event === "stream") {
            streamingRef.current += (data.token as string | undefined) ?? "";
            setStreaming(streamingRef.current);
          } else if (event === "reasoning") {
            streamingRef.current = (data.text as string | undefined) ?? "";
            setStreaming(streamingRef.current);
          } else if (event === "tool_call") {
            flushStreaming();
            setTimeline((prev) => [
              ...prev,
              {
                kind: "action",
                name: (data.name as string | undefined) ?? "",
                args: (data.args as Record<string, unknown> | undefined) ?? {},
              },
            ]);
          } else if (event === "question") {
            flushStreaming();
            setQuestion({
              question: (data.question as string | undefined) ?? "",
              context: data.context as string | undefined,
            });
            setStatus("waiting_for_user");
          } else if (event === "finalize") {
            setResult({
              success: Boolean(data.success),
              reason: (data.reason as string | undefined) ?? "",
            });
          } else if (event === "error") {
            setError((data.message as string | undefined) ?? "Something went wrong.");
            setStatus("error");
          } else if (event === "run_complete") {
            flushStreaming();
            const stopped = Boolean(data.stopped);
            if (stopped) {
              setResult({
                success: false,
                stopped: true,
                reason: (data.reason as string | undefined) ?? "Stopped by you.",
              });
            }
            setStatus((prev) => (prev === "error" ? "error" : stopped ? "stopped" : "done"));
            closeSocket();
          }
        };

        ws.onerror = onFail;

        ws.onclose = () => {
          if (!opened) {
            onFail();
            return;
          }
          setStatus((prev) => (BUSY.includes(prev) ? "done" : prev));
        };
      };

      const scheduleRetry = () => {
        attemptRef.current += 1;
        if (attemptRef.current > MAX_WAKE_ATTEMPTS) {
          setWaking(false);
          setError(
            `Can't reach the agent at ${WS_URL}. The backend looks asleep or down — ` +
              `open the Space to wake it, wait until it shows "Running", then try again.`
          );
          setStatus("error");
          return;
        }
        setWaking(true);
        // The request itself nudges a sleeping host (e.g. HF Spaces) to start booting.
        fetch(WAKE_URL, { mode: "no-cors", cache: "no-store" }).catch(() => {});
        retryTimerRef.current = window.setTimeout(openSocket, WAKE_RETRY_MS);
      };

      openSocket();
    },
    [closeSocket, flushStreaming]
  );

  const answer = useCallback(
    (text: string) => {
      send({ type: "answer", answer: text });
      setQuestion(null);
      setStatus("running");
    },
    [send]
  );

  const stop = useCallback(() => {
    clearRetry();
    setWaking(false);
    const open = wsRef.current?.readyState === WebSocket.OPEN;
    send({ type: "stop" });
    setQuestion(null);
    if (open) {
      setStatus("stopping");
    } else {
      closeSocket(); // nothing connected (e.g. cancelled mid-wake) — end it cleanly
      setStatus("stopped");
    }
  }, [send, clearRetry, closeSocket]);

  useEffect(() => () => closeSocket(), [closeSocket]);

  return {
    status,
    task,
    timeline,
    streaming,
    question,
    result,
    error,
    waking,
    hasFrame,
    pageUrl,
    subscribeFrame,
    start,
    answer,
    stop,
  };
}
