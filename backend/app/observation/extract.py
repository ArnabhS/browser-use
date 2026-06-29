from __future__ import annotations

from app.observation.raw import PageMeta, RawElement

EXTRACT_JS = r"""
() => {
  const INTERACTIVE_TAGS = new Set(['a','button','input','select','textarea','summary']);
  const INTERACTIVE_ROLES = new Set(['button','link','checkbox','radio','tab','menuitem','textbox','combobox','switch','option']);
  // React/RN-web render controls as plain <div>s with no role/cursor/onclick/tabindex — the click
  // handler lives only in the component props React stashes on the DOM node under __reactProps$<hash>
  // (or __reactEventHandlers$ on React 16). RN-web maps onPress→onClick. Detect those handlers so
  // non-semantic buttons (e.g. Flipkart "Add to cart") are visible to the agent.
  const REACT_CLICK = ['onClick','onClickCapture','onMouseDown','onMouseUp','onPointerDown','onPointerUp','onTouchEnd','onResponderRelease'];
  const hasReactClickHandler = (el) => {
    let props = null;
    for (const k of Object.keys(el)) {
      if (k.startsWith('__reactProps$') || k.startsWith('__reactEventHandlers$')) { props = el[k]; break; }
    }
    if (!props) return false;
    for (const h of REACT_CLICK) if (typeof props[h] === 'function') return true;
    return false;
  };
  const isInteractive = (el) => {
    const tag = el.tagName.toLowerCase();
    if (INTERACTIVE_TAGS.has(tag)) return true;
    const role = el.getAttribute('role');
    if (role && INTERACTIVE_ROLES.has(role)) return true;
    if (el.hasAttribute('onclick')) return true;
    if (el.getAttribute('contenteditable') === 'true') return true;
    if (el.tabIndex >= 0 && tag !== 'body' && tag !== 'html') return true;
    if (hasReactClickHandler(el)) return true;
    return false;
  };
  const name = (el) => (
    el.getAttribute('aria-label') || el.getAttribute('placeholder') ||
    el.getAttribute('alt') || el.getAttribute('title') ||
    (el.innerText || '').trim() || el.value || ''
  ).trim().replace(/\s+/g, ' ').slice(0, 200);
  // An element is occluded only if EVERY sampled point of its box is blocked by an unrelated
  // element that is a genuine COVERING SURFACE (a modal/overlay enclosing it, ≥2× its area).
  // A single centre point + an "anything not self/child" rule (the old logic) culled visible,
  // clickable controls whenever their centre landed on an overlapping wrapper/icon/sibling div
  // — e.g. Flipkart's header "Cart" link or a React click-catcher. Sample 5 points and treat
  // same-spot overlaps as reachable (a trusted click at those coords actuates them anyway).
  const isOccluded = (el, r) => {
    if (r.width <= 0 || r.height <= 0) return false;
    const w = r.width, h = r.height;
    const pts = [
      [r.left + w / 2,    r.top + h / 2],
      [r.left + w * 0.5,  r.top + h * 0.15],
      [r.left + w * 0.5,  r.top + h * 0.85],
      [r.left + w * 0.15, r.top + h * 0.5],
      [r.left + w * 0.85, r.top + h * 0.5],
    ];
    let tested = false;
    for (const [px, py] of pts) {
      if (px < 0 || py < 0 || px >= innerWidth || py >= innerHeight) continue;
      const t = document.elementFromPoint(px, py);
      if (!t) continue;
      tested = true;
      if (t === el || el.contains(t) || t.contains(el)) return false;  // self / child / wrapper
      const tr = t.getBoundingClientRect();
      const covers = tr.left <= r.left + 1 && tr.top <= r.top + 1 &&
                     tr.right >= r.right - 1 && tr.bottom >= r.bottom - 1 &&
                     (tr.width * tr.height) >= (w * h) * 2;
      if (!covers) return false;   // overlapping but not a covering surface → reachable
    }
    return tested;   // off-screen (nothing tested) is NOT occlusion — let visibility handle it
  };
  const out = [];
  for (const el of document.querySelectorAll('*')) {
    if (!isInteractive(el)) continue;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    const visible = s.display !== 'none' && s.visibility !== 'hidden' &&
                    parseFloat(s.opacity || '1') > 0 && r.width > 0 && r.height > 0;
    const inViewport = r.bottom > 0 && r.right > 0 &&
                       r.top < innerHeight && r.left < innerWidth;
    const occluded = isOccluded(el, r);
    out.push({
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || el.tagName.toLowerCase(),
      name: name(el),
      value: (el.value || '').slice(0, 200) || null,
      x: r.left, y: r.top, width: r.width, height: r.height,
      visible, in_viewport: inViewport, occluded,
    });
  }
  return {
    url: location.href, title: document.title,
    viewport_width: innerWidth, viewport_height: innerHeight,
    scroll_x: window.scrollX, scroll_y: window.scrollY,
    elements: out,
  };
}
"""


# Diagnostic: find DOM elements (ANY tag) whose text contains `focus`, and report why the
# extractor did or didn't pick each one up. This distinguishes "never extracted" (would_extract
# false — it's a div with a React handler, no role/onclick/tabindex) from "extracted then culled"
# (would_extract true, but hit-test returns something else → occlusion drops it).
_PROBE_JS = r"""
(focus) => {
  const f = (focus || '').toLowerCase();
  const ITAGS = new Set(['a','button','input','select','textarea','summary']);
  const IROLES = new Set(['button','link','checkbox','radio','tab','menuitem','textbox','combobox','switch','option']);
  const wouldExtract = (el) => {
    const tag = el.tagName.toLowerCase();
    if (ITAGS.has(tag)) return true;
    const role = el.getAttribute('role');
    if (role && IROLES.has(role)) return true;
    if (el.hasAttribute('onclick')) return true;
    if (el.getAttribute('contenteditable') === 'true') return true;
    if (el.tabIndex >= 0 && tag !== 'body' && tag !== 'html') return true;
    return false;
  };
  const out = [];
  for (const el of document.querySelectorAll('*')) {
    const txt = ((el.innerText || el.value || el.getAttribute('aria-label') || '') + '').trim();
    if (!txt || !txt.toLowerCase().includes(f)) continue;
    // keep only the deepest match — skip ancestors that contain the text via a descendant
    if ([...el.children].some(c => (((c.innerText || '') + '')).toLowerCase().includes(f))) continue;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const topEl = (r.width > 0 && r.height > 0) ? document.elementFromPoint(cx, cy) : null;
    out.push({
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || '',
      text: txt.replace(/\s+/g, ' ').slice(0, 60),
      would_extract: wouldExtract(el),
      has_onclick: el.hasAttribute('onclick'),
      tabindex: el.tabIndex,
      cursor: s.cursor,
      position: s.position,
      display: s.display, visibility: s.visibility, opacity: s.opacity,
      rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
      hit: topEl ? (topEl.tagName.toLowerCase() + (topEl.id ? '#' + topEl.id : '')) : null,
      hit_is_self_or_child: !!(topEl && (topEl === el || el.contains(topEl) || topEl.contains(el))),
    });
    if (out.length >= 25) break;
  }
  return out;
}
"""


async def probe_dom(page, focus: str) -> list[dict]:
    """Ground-truth scan for diagnostics: every DOM node whose text contains `focus`, with the
    reasons the funnel would keep or drop it. Best-effort — returns [] on any failure."""
    try:
        return await page.evaluate(_PROBE_JS, focus)
    except Exception:
        return []


_NAV_MARKERS = (
    "execution context was destroyed",
    "navigating and changing the content",
    "frame was detached",
    "cannot find context",
)


def _is_navigation_error(exc: Exception) -> bool:
    """A page.evaluate that raced an in-flight navigation (the JS context was torn down)."""
    msg = str(exc).lower()
    return any(m in msg for m in _NAV_MARKERS)


async def extract(page, *, retries: int = 3) -> tuple[list[RawElement], PageMeta]:
    """Run the DOM funnel. Resilient to navigations (e.g. Enter submits a search → the page
    navigates mid-evaluate): on a destroyed context, wait for the new page to load and retry."""
    last_exc: Exception | None = None
    for attempt in range(retries):
        # Best-effort: don't evaluate against a half-built document.
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        try:
            data = await page.evaluate(EXTRACT_JS)
        except Exception as exc:
            if not _is_navigation_error(exc) or attempt == retries - 1:
                raise
            last_exc = exc
            try:  # the page is navigating — let it settle, then retry against the new context
                await page.wait_for_load_state("load", timeout=10000)
            except Exception:
                pass
            continue
        raw = [RawElement(**e) for e in data["elements"]]
        meta = PageMeta(
            url=data["url"], title=data["title"],
            viewport_width=data["viewport_width"], viewport_height=data["viewport_height"],
            scroll_x=data["scroll_x"], scroll_y=data["scroll_y"],
        )
        return raw, meta
    raise last_exc if last_exc else RuntimeError("extract failed")
