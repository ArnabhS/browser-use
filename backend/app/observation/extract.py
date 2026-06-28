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
    out.push({
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || el.tagName.toLowerCase(),
      name: name(el),
      value: (el.value || '').slice(0, 200) || null,
      x: r.left, y: r.top, width: r.width, height: r.height,
      visible, in_viewport: inViewport,
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


async def extract(page) -> tuple[list[RawElement], PageMeta]:
    data = await page.evaluate(EXTRACT_JS)
    raw = [RawElement(**e) for e in data["elements"]]
    meta = PageMeta(
        url=data["url"], title=data["title"],
        viewport_width=data["viewport_width"], viewport_height=data["viewport_height"],
        scroll_x=data["scroll_x"], scroll_y=data["scroll_y"],
    )
    return raw, meta
