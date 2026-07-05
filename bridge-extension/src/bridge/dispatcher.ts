// dispatch(): turn an ActionCall (referencing elements by index) into trusted CDP input on the page.
// Coordinates come from the hidden index→coord map built by the funnel. Matches the backend action
// vocabulary (navigate/click/type/scroll/press_key/clear/wait_for/extract).
import type { Cdp } from "./cdp";
import type { ElementCoords } from "./funnel";

export interface ActionCallShape {
  name: string;
  args: Record<string, any>;
}

export interface ActionResultShape {
  success: boolean;
  reason?: string;
  errorCode?: string | null;
}

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

const KEYS: Record<string, { key: string; code: string; vk: number }> = {
  Enter: { key: "Enter", code: "Enter", vk: 13 },
  Delete: { key: "Delete", code: "Delete", vk: 46 },
  Backspace: { key: "Backspace", code: "Backspace", vk: 8 },
  Tab: { key: "Tab", code: "Tab", vk: 9 },
  Escape: { key: "Escape", code: "Escape", vk: 27 },
  ArrowDown: { key: "ArrowDown", code: "ArrowDown", vk: 40 },
  ArrowUp: { key: "ArrowUp", code: "ArrowUp", vk: 38 },
};

async function clickAt(cdp: Cdp, x: number, y: number, clickCount = 1): Promise<void> {
  const base = { x, y, button: "left", clickCount, buttons: 1 };
  await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed", ...base });
  await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased", ...base });
}

async function pressKey(cdp: Cdp, name: string): Promise<void> {
  const k = KEYS[name] ?? { key: name, code: name, vk: 0 };
  const base = { key: k.key, code: k.code, windowsVirtualKeyCode: k.vk, nativeVirtualKeyCode: k.vk };
  await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", ...base });
  await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", ...base });
}

export async function dispatch(
  cdp: Cdp,
  call: ActionCallShape,
  coords: ElementCoords
): Promise<ActionResultShape> {
  const { name } = call;
  const args = call.args ?? {};
  const coordFor = (idx: any) => coords[Number(idx)];

  if (name === "navigate") {
    await cdp.send("Page.navigate", { url: String(args.url) });
    await sleep(700);
    return { success: true, reason: `navigated to ${args.url}` };
  }

  if (name === "click" || name === "type") {
    const c = coordFor(args.index);
    if (!c) return { success: false, reason: `stale index ${args.index}`, errorCode: "STALE_INDEX" };
    await clickAt(cdp, c.x, c.y);
    if (name === "type") await cdp.send("Input.insertText", { text: String(args.text ?? "") });
    await sleep(250);
    return { success: true, reason: `${name} at [${args.index}]` };
  }

  if (name === "scroll") {
    const dir = args.direction === "up" ? -1 : 1;
    const steps = Number(args.amount ?? 1) || 1;
    const c = args.index != null ? coordFor(args.index) : null;
    const x = c ? c.x : 20;
    const y = c ? c.y : 20;
    await cdp.send("Input.dispatchMouseEvent", {
      type: "mouseWheel",
      x,
      y,
      deltaX: 0,
      deltaY: dir * 600 * steps,
    });
    await sleep(250);
    return { success: true, reason: `scrolled ${args.direction ?? "down"}` };
  }

  if (name === "press_key") {
    await pressKey(cdp, String(args.key));
    await sleep(250);
    return { success: true, reason: `pressed ${args.key}` };
  }

  if (name === "long_press") {
    const c = coordFor(args.index);
    if (!c) return { success: false, reason: `stale index ${args.index}`, errorCode: "STALE_INDEX" };
    const dur = Math.min(Math.max(Number(args.duration_ms ?? 800), 0), 5000);
    const base = { x: c.x, y: c.y, button: "left", clickCount: 1, buttons: 1 };
    await cdp.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: c.x, y: c.y });
    await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed", ...base });
    await sleep(dur); // hold
    await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased", ...base });
    await sleep(150);
    return { success: true, reason: `long-pressed [${args.index}] for ${dur}ms` };
  }

  if (name === "clear") {
    const c = coordFor(args.index);
    if (!c) return { success: false, reason: `stale index ${args.index}`, errorCode: "STALE_INDEX" };
    await clickAt(cdp, c.x, c.y, 3); // triple-click selects all
    await pressKey(cdp, "Delete");
    await sleep(150);
    return { success: true, reason: `cleared [${args.index}]` };
  }

  if (name === "wait_for") {
    await sleep(Math.min(Number(args.seconds ?? 1) * 1000, 10_000));
    return { success: true, reason: "waited" };
  }

  if (name === "extract") {
    const text = await cdp.eval("document.body ? document.body.innerText.slice(0, 4000) : ''");
    return { success: true, reason: String(text ?? "") };
  }

  return {
    success: false,
    reason: `action '${name}' is not supported by the bridge extension yet (M1)`,
    errorCode: "UNSUPPORTED_ACTION",
  };
}
