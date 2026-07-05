// Service-worker glue: click the toolbar icon to put a tab under agent control. Attaches
// chrome.debugger, opens the WS to the backend, and wires observe/act/navigate/tabs to the funnel +
// dispatcher. Click again (or cancel the debugger banner) to release the tab.
import { attach, detach, enableDomains, makeCdp, type Cdp } from "../bridge/cdp";
import { BACKEND_WS } from "../bridge/config";
import { dispatch } from "../bridge/dispatcher";
import { observe, type ElementCoords } from "../bridge/funnel";
import { BridgeClient, type BridgeHandlers } from "../bridge/ws-client";

interface Controlled {
  tabId: number;
  cdp: Cdp;
  client: BridgeClient;
  coords: ElementCoords;
}

let active: Controlled | null = null;

function setBadge(on: boolean): void {
  try {
    chrome.action.setBadgeText({ text: on ? "ON" : "" });
    chrome.action.setBadgeBackgroundColor({ color: on ? "#16a34a" : "#000000" });
  } catch {
    /* badge is cosmetic */
  }
}

async function stop(): Promise<void> {
  if (!active) return;
  const { tabId, client } = active;
  active = null;
  try {
    client.close();
  } catch {
    /* ignore */
  }
  await detach(tabId);
  setBadge(false);
}

async function startControl(tabId: number): Promise<void> {
  if (active) await stop();

  await attach(tabId);
  const cdp = makeCdp(tabId);
  await enableDomains(cdp);

  const controlled: Controlled = { tabId, cdp, client: null as unknown as BridgeClient, coords: {} };

  const handlers: BridgeHandlers = {
    async observe() {
      const { observation, coords, screenshot } = await observe(cdp);
      controlled.coords = coords; // freshest map wins — indices are not stable across turns
      if (screenshot) controlled.client.sendFrame(screenshot, { url: observation.url });
      return observation;
    },
    async act(payload) {
      return dispatch(cdp, { name: payload?.name, args: payload?.args ?? {} }, controlled.coords);
    },
    async navigate(payload) {
      return dispatch(cdp, { name: "navigate", args: { url: payload?.url } }, controlled.coords);
    },
    async tabs() {
      const tabs = await chrome.tabs.query({});
      return {
        tabs: tabs.map((t) => ({
          id: t.id ?? 0,
          title: t.title ?? "",
          url: t.url ?? "",
          active: Boolean(t.active),
        })),
      };
    },
  };

  const client = new BridgeClient(
    BACKEND_WS,
    handlers,
    { userAgent: navigator.userAgent, tabId },
    (connected) => setBadge(connected)
  );
  controlled.client = client;
  active = controlled;
  client.connect();
  setBadge(true);
}

chrome.action.onClicked.addListener((tab) => {
  const tabId = tab.id;
  if (typeof tabId !== "number") return;
  if (active && active.tabId === tabId) {
    void stop();
  } else {
    void startControl(tabId).catch((e) => {
      console.error("[bridge] failed to control tab", e);
      void stop();
    });
  }
});

// If the user cancels the "debugging this browser" banner (or the tab detaches), release cleanly.
chrome.debugger.onDetach.addListener((source) => {
  if (active && source.tabId === active.tabId) void stop();
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (active && active.tabId === tabId) void stop();
});
