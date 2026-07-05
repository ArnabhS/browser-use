import { describe, expect, it } from "vitest";

import type { Cdp } from "./cdp";
import { dispatch } from "./dispatcher";

function fakeCdp() {
  const calls: { method: string; params: any }[] = [];
  const cdp: Cdp = {
    send: async (method, params = {}) => {
      calls.push({ method, params });
      return {};
    },
    eval: async (expr) => {
      calls.push({ method: "eval", params: expr });
      return "PAGE TEXT";
    },
  };
  return { cdp, calls };
}

const coords = { 0: { x: 100, y: 200 }, 1: { x: 50, y: 60 } };

describe("dispatch", () => {
  it("navigate → Page.navigate with the url", async () => {
    const { cdp, calls } = fakeCdp();
    const res = await dispatch(cdp, { name: "navigate", args: { url: "https://x.test" } }, coords);
    expect(res.success).toBe(true);
    expect(calls[0]).toEqual({ method: "Page.navigate", params: { url: "https://x.test" } });
  });

  it("click → trusted press+release at the mapped coordinates", async () => {
    const { cdp, calls } = fakeCdp();
    const res = await dispatch(cdp, { name: "click", args: { index: 0 } }, coords);
    expect(res.success).toBe(true);
    const mouse = calls.filter((c) => c.method === "Input.dispatchMouseEvent");
    expect(mouse[0].params).toMatchObject({ type: "mousePressed", x: 100, y: 200, button: "left" });
    expect(mouse[1].params).toMatchObject({ type: "mouseReleased", x: 100, y: 200 });
  });

  it("type → click the field, then insertText", async () => {
    const { cdp, calls } = fakeCdp();
    await dispatch(cdp, { name: "type", args: { index: 1, text: "hello" } }, coords);
    expect(calls.some((c) => c.method === "Input.dispatchMouseEvent")).toBe(true);
    const insert = calls.find((c) => c.method === "Input.insertText");
    expect(insert?.params).toEqual({ text: "hello" });
  });

  it("stale index → typed failure and NO input dispatched", async () => {
    const { cdp, calls } = fakeCdp();
    const res = await dispatch(cdp, { name: "click", args: { index: 99 } }, coords);
    expect(res.success).toBe(false);
    expect(res.errorCode).toBe("STALE_INDEX");
    expect(calls.length).toBe(0);
  });

  it("press_key Enter → keyDown/keyUp with the right virtual key code", async () => {
    const { cdp, calls } = fakeCdp();
    await dispatch(cdp, { name: "press_key", args: { key: "Enter" } }, coords);
    const keys = calls.filter((c) => c.method === "Input.dispatchKeyEvent");
    expect(keys[0].params).toMatchObject({ type: "keyDown", key: "Enter", windowsVirtualKeyCode: 13 });
    expect(keys[1].params).toMatchObject({ type: "keyUp", key: "Enter" });
  });

  it("scroll down → mouseWheel with positive deltaY", async () => {
    const { cdp, calls } = fakeCdp();
    await dispatch(cdp, { name: "scroll", args: { direction: "down", amount: 2 } }, coords);
    const wheel = calls.find(
      (c) => c.method === "Input.dispatchMouseEvent" && c.params.type === "mouseWheel"
    );
    expect(wheel?.params.deltaY).toBeGreaterThan(0);
  });

  it("long_press → press, hold, then release at the mapped coords", async () => {
    const { cdp, calls } = fakeCdp();
    const res = await dispatch(cdp, { name: "long_press", args: { index: 0, duration_ms: 50 } }, coords);
    expect(res.success).toBe(true);
    const mouse = calls.filter((c) => c.method === "Input.dispatchMouseEvent");
    const press = mouse.find((c) => c.params.type === "mousePressed");
    const release = mouse.find((c) => c.params.type === "mouseReleased");
    expect(press?.params).toMatchObject({ x: 100, y: 200 });
    expect(release?.params).toMatchObject({ x: 100, y: 200 });
    expect(mouse.indexOf(press!)).toBeLessThan(mouse.indexOf(release!)); // held: press before release
  });

  it("long_press with a stale index → typed failure, no input dispatched", async () => {
    const { cdp, calls } = fakeCdp();
    const res = await dispatch(cdp, { name: "long_press", args: { index: 99 } }, coords);
    expect(res.success).toBe(false);
    expect(res.errorCode).toBe("STALE_INDEX");
    expect(calls.length).toBe(0);
  });

  it("unknown action → UNSUPPORTED_ACTION failure", async () => {
    const { cdp } = fakeCdp();
    const res = await dispatch(cdp, { name: "teleport", args: {} }, coords);
    expect(res.success).toBe(false);
    expect(res.errorCode).toBe("UNSUPPORTED_ACTION");
  });
});
