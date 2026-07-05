// observe(): run the in-page collector, capture a screenshot, and assemble the Observation contract
// + the hidden index→coordinate map (kept here in the extension, never sent to the backend).
import { PROTOCOL_VERSION } from "@browser-agent/contracts";

import type { Cdp } from "./cdp";
import { collectorExpression, type RawSnapshot } from "./collector";

export interface ElementCoords {
  [index: number]: { x: number; y: number };
}

export interface ObservePayload {
  protocolVersion: string;
  url: string;
  title: string;
  viewport: { width: number; height: number; scrollX: number; scrollY: number };
  elements: { index: number; role: string; name: string; value: string | null }[];
  tabs: unknown[];
  screenshotRef: string | null;
  droppedCount: number;
}

export interface ObserveResult {
  observation: ObservePayload;
  coords: ElementCoords;
  screenshot: string | null; // base64 jpeg for the cockpit live view (sent as a `frame`)
}

export async function observe(cdp: Cdp): Promise<ObserveResult> {
  const snap = (await cdp.eval(collectorExpression())) as RawSnapshot;
  const items = snap?.items ?? [];

  const coords: ElementCoords = {};
  const elements = items.map((it, i) => {
    coords[i] = { x: it.centerX, y: it.centerY };
    return { index: i, role: it.role, name: it.name, value: it.value };
  });

  let screenshot: string | null = null;
  try {
    const shot = await cdp.send("Page.captureScreenshot", { format: "jpeg", quality: 50 });
    screenshot = shot?.data ?? null;
  } catch {
    screenshot = null; // best-effort live view; observation still returns
  }

  const observation: ObservePayload = {
    protocolVersion: PROTOCOL_VERSION,
    url: snap?.url ?? "",
    title: snap?.title ?? "",
    viewport: snap?.viewport ?? { width: 0, height: 0, scrollX: 0, scrollY: 0 },
    elements,
    tabs: [],
    screenshotRef: null,
    droppedCount: 0,
  };

  return { observation, coords, screenshot };
}
