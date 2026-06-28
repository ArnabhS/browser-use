from __future__ import annotations

from app.observation.raw import PageMeta, RawElement

EXTRACT_JS = r"""
() => {
  const INTERACTIVE_TAGS = new Set(['a','button','input','select','textarea','summary']);
  const INTERACTIVE_ROLES = new Set(['button','link','checkbox','radio','tab','menuitem','textbox','combobox','switch','option']);
  const isInteractive = (el) => {
    const tag = el.tagName.toLowerCase();
    if (INTERACTIVE_TAGS.has(tag)) return true;
    const role = el.getAttribute('role');
    if (role && INTERACTIVE_ROLES.has(role)) return true;
    if (el.hasAttribute('onclick')) return true;
    if (el.getAttribute('contenteditable') === 'true') return true;
    if (el.tabIndex >= 0 && tag !== 'body' && tag !== 'html') return true;
    return false;
  };
  const name = (el) => (
    el.getAttribute('aria-label') || el.getAttribute('placeholder') ||
    el.getAttribute('alt') || el.getAttribute('title') ||
    (el.innerText || '').trim() || el.value || ''
  ).trim().replace(/\s+/g, ' ').slice(0, 200);
  const out = [];
  for (const el of document.querySelectorAll('*')) {
    if (!isInteractive(el)) continue;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    const visible = s.display !== 'none' && s.visibility !== 'hidden' &&
                    parseFloat(s.opacity || '1') > 0 && r.width > 0 && r.height > 0;
    const inViewport = r.bottom > 0 && r.right > 0 &&
                       r.top < innerHeight && r.left < innerWidth;
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const topEl = (r.width > 0 && r.height > 0) ? document.elementFromPoint(cx, cy) : null;
    const occluded = !!(topEl && topEl !== el && !el.contains(topEl) && !topEl.contains(el));
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
