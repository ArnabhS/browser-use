import { describe, expect, it, vi } from "vitest";

import { handleRequest, type BridgeHandlers } from "./ws-client";

function handlers(over: Partial<BridgeHandlers> = {}): BridgeHandlers {
  return {
    observe: async () => ({ url: "https://u.test", elements: [] }),
    act: async () => ({ success: true }),
    navigate: async () => ({ success: true }),
    tabs: async () => ({ tabs: [] }),
    ...over,
  };
}

describe("handleRequest", () => {
  it("routes observe and echoes the id in a result envelope", async () => {
    const reply = await handleRequest(
      { type: "observe", id: "r1", payload: { includeSom: true } },
      handlers()
    );
    expect(reply.type).toBe("result");
    expect(reply.id).toBe("r1");
    expect(reply.payload.url).toBe("https://u.test");
  });

  it("passes the payload through to the handler", async () => {
    const spy = vi.fn(async (p: any) => ({ success: true, echoed: p.args.index }));
    const reply = await handleRequest(
      { type: "act", id: "a1", payload: { name: "click", args: { index: 2 } } },
      handlers({ act: spy as any })
    );
    expect(spy).toHaveBeenCalledWith({ name: "click", args: { index: 2 } });
    expect(reply.payload.echoed).toBe(2);
  });

  it("returns an error envelope (same id) when the handler throws", async () => {
    const reply = await handleRequest(
      { type: "act", id: "a2", payload: {} },
      handlers({
        act: async () => {
          throw new Error("boom");
        },
      })
    );
    expect(reply.type).toBe("error");
    expect(reply.id).toBe("a2");
    expect(reply.payload.message).toContain("boom");
    expect(reply.payload.errorCode).toBe("EXT_ERROR");
  });

  it("ignores non-request messages (results, pings, junk)", async () => {
    expect(await handleRequest({ type: "result", id: "x" }, handlers())).toBeNull();
    expect(await handleRequest({ type: "ping" }, handlers())).toBeNull();
    expect(await handleRequest(null, handlers())).toBeNull();
    expect(await handleRequest({ nope: 1 }, handlers())).toBeNull();
  });
});
