// Thin promise wrapper over chrome.debugger so the funnel/dispatcher can `await cdp.send(...)`.
// Attaching shows Chrome's "extension is debugging this browser" banner — expected and honest.
import { CDP_VERSION } from "./config";

export interface Cdp {
  send(method: string, params?: object): Promise<any>;
  /** Runtime.evaluate in the page's main world, returned by value. */
  eval(expression: string): Promise<any>;
}

export function makeCdp(tabId: number): Cdp {
  const target: chrome.debugger.Debuggee = { tabId };
  const send = (method: string, params: object = {}): Promise<any> =>
    new Promise((resolve, reject) => {
      chrome.debugger.sendCommand(target, method, params, (result) => {
        const err = chrome.runtime.lastError;
        if (err) reject(new Error(err.message));
        else resolve(result);
      });
    });
  const evalExpr = async (expression: string): Promise<any> => {
    const r = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (r?.exceptionDetails) throw new Error(r.exceptionDetails.text || "page evaluate failed");
    return r?.result?.value;
  };
  return { send, eval: evalExpr };
}

export function attach(tabId: number): Promise<void> {
  return new Promise((resolve, reject) => {
    chrome.debugger.attach({ tabId }, CDP_VERSION, () => {
      const err = chrome.runtime.lastError;
      if (err) reject(new Error(err.message));
      else resolve();
    });
  });
}

export function detach(tabId: number): Promise<void> {
  return new Promise((resolve) => {
    chrome.debugger.detach({ tabId }, () => {
      void chrome.runtime.lastError; // ignore "not attached"
      resolve();
    });
  });
}

/** Enable the CDP domains the funnel/dispatcher rely on. Best-effort. */
export async function enableDomains(cdp: Cdp): Promise<void> {
  for (const d of ["Page", "Runtime", "DOM"]) {
    try {
      await cdp.send(`${d}.enable`);
    } catch {
      /* domain may already be enabled */
    }
  }
}
