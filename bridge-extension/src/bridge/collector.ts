// The minimal funnel (spec §7): a self-contained function that runs IN THE PAGE via Runtime.evaluate
// and returns a compact list of visible interactables with viewport-center coordinates. The raw DOM
// never leaves the page — only this list crosses the wire.
//
// It MUST stay self-contained (all helpers nested) so `collectInteractables.toString()` serializes to
// a complete, closure-free function. It's also exported directly so it can be unit-tested against a
// fixture DOM (with stubbed geometry, since jsdom/happy-dom do no layout).

export interface RawItem {
  role: string;
  name: string;
  value: string | null;
  centerX: number;
  centerY: number;
}

export interface RawSnapshot {
  url: string;
  title: string;
  viewport: { width: number; height: number; scrollX: number; scrollY: number };
  items: RawItem[];
}

export function collectInteractables(doc: Document, win: Window): RawSnapshot {
  const SEL =
    'a[href],button,input,select,textarea,[role="button"],[role="link"],[role="textbox"],' +
    '[role="checkbox"],[role="tab"],[role="menuitem"],[role="option"],[contenteditable="true"],[onclick]';
  const vw = win.innerWidth || 0;
  const vh = win.innerHeight || 0;

  const truncate = (s: string, n: number): string => (s.length > n ? s.slice(0, n - 1) + "…" : s);

  const roleOf = (el: Element): string => {
    const explicit = el.getAttribute("role");
    if (explicit) return explicit;
    const tag = el.tagName.toLowerCase();
    if (tag === "a") return "link";
    if (tag === "button") return "button";
    if (tag === "select") return "combobox";
    if (tag === "textarea") return "textbox";
    if (tag === "input") {
      const t = (el.getAttribute("type") || "text").toLowerCase();
      if (t === "checkbox") return "checkbox";
      if (t === "radio") return "radio";
      if (t === "submit" || t === "button" || t === "reset") return "button";
      return "textbox";
    }
    return "generic";
  };

  const nameOf = (el: Element): string => {
    const pick = (v: string | null): string => (v && v.trim() ? truncate(v.trim(), 120) : "");
    const aria = pick(el.getAttribute("aria-label"));
    if (aria) return aria;
    const text = pick((el.textContent || "").replace(/\s+/g, " "));
    if (text) return text;
    const ph = pick(el.getAttribute("placeholder"));
    if (ph) return ph;
    const title = pick(el.getAttribute("title"));
    if (title) return title;
    const alt = pick(el.getAttribute("alt"));
    if (alt) return alt;
    const val = (el as HTMLInputElement).value;
    return pick(val != null ? String(val) : null);
  };

  const valueOf = (el: Element): string | null => {
    const tag = el.tagName.toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") {
      const v = (el as HTMLInputElement).value;
      return v ? truncate(String(v), 120) : null;
    }
    return null;
  };

  const items: RawItem[] = [];
  const nodes = Array.prototype.slice.call(doc.querySelectorAll(SEL)) as Element[];
  for (const el of nodes) {
    // Anti-bot pages (PerimeterX) plant elements with a nuked prototype chain — every property
    // reads undefined. One hostile element must never kill the whole observe.
    try {
      if (typeof (el as HTMLElement).tagName !== "string") continue;
      const rect = (el as HTMLElement).getBoundingClientRect();
      if (rect.width <= 1 || rect.height <= 1) continue; // zero-size
      if (rect.bottom < 0 || rect.right < 0 || rect.top > vh || rect.left > vw) continue; // off-screen
      const style = win.getComputedStyle(el as HTMLElement);
      if (style) {
        if (style.display === "none" || style.visibility === "hidden" || style.visibility === "collapse") continue;
        if (parseFloat(style.opacity || "1") === 0) continue;
      }
      if ((el as HTMLElement).hidden) continue;
      const cx = Math.round(Math.min(Math.max(rect.left + rect.width / 2, 0), vw));
      const cy = Math.round(Math.min(Math.max(rect.top + rect.height / 2, 0), vh));
      items.push({ role: roleOf(el), name: nameOf(el), value: valueOf(el), centerX: cx, centerY: cy });
    } catch {
      /* pathological element — skip, never fatal */
    }
  }

  return {
    url: (doc.location && doc.location.href) || "",
    title: doc.title || "",
    viewport: { width: vw, height: vh, scrollX: Math.round(win.scrollX || 0), scrollY: Math.round(win.scrollY || 0) },
    items,
  };
}

/** The expression handed to Runtime.evaluate — an IIFE over the live document/window. */
export function collectorExpression(): string {
  return `(${collectInteractables.toString()})(document, window)`;
}
