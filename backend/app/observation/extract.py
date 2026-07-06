from __future__ import annotations

import asyncio

from app.observation.raw import PageMeta, RawElement

# Runs via CDP Runtime.evaluate with includeCommandLineAPI (getEventListeners is a DevTools-only
# helper, not reachable from page script). It records every element carrying a real click/pointer
# listener into a WeakSet on window, which EXTRACT_JS then reads — so a plain <div>/<span> wired up
# with addEventListener('click', …) by ANY framework becomes interactable. Fresh WeakSet each call
# (no stale markers, no DOM mutation). 10k-element guard mirrors browser-use.
LISTENER_TAG_JS = r"""
(() => {
  try {
    const set = new WeakSet();
    const all = document.querySelectorAll('*');
    if (all.length <= 10000 && typeof getEventListeners === 'function') {
      for (const el of all) {
        try {
          const L = getEventListeners(el);
          if (L && (L.click || L.mousedown || L.mouseup || L.pointerdown || L.pointerup)) set.add(el);
        } catch (e) {}
      }
    }
    window.__somListeners = set;
    return true;
  } catch (e) { return false; }
})()
"""

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
    // Real click/pointer listeners found by a CDP getEventListeners pre-pass (see LISTENER_TAG_JS)
    // and stashed on window — catches non-semantic clickables from ANY framework (Vue, Svelte,
    // vanilla), not just React, e.g. a bare <span> with addEventListener('click', …).
    try { if (window.__somListeners && window.__somListeners.has(el)) return true; } catch (e) {}
    return false;
  };
  // The VISIBLE text is ground truth for the agent (it cross-references the screenshot / SoM
  // overlay). Prefer it whenever it's a real textual label — this beats a MISLEADING aria-label,
  // e.g. quashbugs.com's header <a aria-label="Get Early Access To Automate">Book a Demo</a>, where
  // trusting aria-label made the agent unable to find (or click) the button it was told to press.
  // Fall back to aria-label/placeholder/alt/title/value only for icon-only, glyph, or empty controls
  // (innerText has no word characters).
  const name = (el) => {
    const clean = (s) => (s || '').trim().replace(/\s+/g, ' ');
    // Form fields are usually named by an ASSOCIATED <label> (for=… or wrapping) — HubSpot et al.
    // set no placeholder/aria-label at all, which left every field a blank `input ""`.
    const labelText = (el) => {
      try {
        if (el.labels && el.labels.length) return clean(el.labels[0].innerText);
        const ids = el.getAttribute('aria-labelledby');
        if (ids) {
          return clean(ids.split(/\s+/)
            .map((id) => { const n = document.getElementById(id); return n ? n.innerText : ''; })
            .join(' '));
        }
      } catch (e) { /* labels not supported on this element */ }
      return '';
    };
    const txt = clean(el.innerText);
    const label = /[a-z0-9]/i.test(txt)
      ? txt
      : (clean(el.getAttribute('aria-label')) || labelText(el) || clean(el.getAttribute('placeholder')) ||
         clean(el.getAttribute('alt')) || clean(el.getAttribute('title')) || txt || clean(el.value));
    return label.slice(0, 200);
  };
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
      // Pierce shadow roots: document.elementFromPoint returns the shadow HOST, so a shadow-DOM
      // control would test against its own host and get wrongly culled. Descend to the real
      // topmost node so the self/child checks below operate inside the shadow tree.
      let t = document.elementFromPoint(px, py);
      while (t && t.shadowRoot) {
        const inner = t.shadowRoot.elementFromPoint(px, py);
        if (!inner || inner === t) break;
        t = inner;
      }
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
  // Walk the whole tree INCLUDING open shadow roots — querySelectorAll('*') stops at shadow
  // boundaries, so web-component controls (many enterprise/banking widgets, some cookie banners)
  // were invisible. Closed shadow roots are unreachable from page script; leave those to CDP.
  const deepQueryAll = (root) => {
    const acc = [];
    const walk = (node) => {
      let els;
      try { els = node.querySelectorAll('*'); } catch (e) { return; }
      for (const el of els) {
        acc.push(el);
        if (el.shadowRoot) walk(el.shadowRoot);
      }
    };
    walk(root);
    return acc;
  };
  const out = [];
  for (const el of deepQueryAll(document)) {
    // Anti-bot pages (PerimeterX — e.g. Skyscanner's captcha) plant elements with a nuked
    // prototype chain: every property reads undefined and naive crawlers crash. One hostile
    // element must never kill the whole observe — skip it and keep extracting.
    try {
      if (typeof el.tagName !== 'string') continue;
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
    } catch (e) { /* pathological element — skip, never fatal */ }
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


# Child-frame extraction guards: skip tracking pixels / hidden ad frames, and cap the frame count so
# an ad-riddled page can't stall observe.
_MAX_CHILD_FRAMES = 12
_MIN_FRAME_SIZE = 40.0
_FRAME_EVAL_TIMEOUT_S = 5.0


async def _extract_child_frames(page, meta: PageMeta) -> list[RawElement]:
    """Run EXTRACT_JS inside every real-sized child iframe (HubSpot/Typeform/Stripe embeds — e.g.
    the quashbugs.com contact form) and merge the results, offsetting each element by the iframe's
    position so its coordinates are main-viewport coordinates. Trusted clicks/typing then land
    inside the frame with no further routing — the browser does it. Works cross-origin: Playwright
    evaluates per-frame over CDP, and frame_element().bounding_box() is main-frame-relative (so
    nested frames need no cumulative math). Best-effort per frame: a broken/mid-navigation frame is
    skipped, never fatal."""
    out: list[RawElement] = []
    extracted = 0
    frames = getattr(page, "frames", None) or []  # fakes/tests may have no frame tree
    for frame in frames:
        if frame == page.main_frame or frame.is_detached():
            continue
        if extracted >= _MAX_CHILD_FRAMES:
            break
        try:
            el = await frame.frame_element()
            box = await el.bounding_box()  # None when the iframe is hidden (display:none etc.)
        except Exception:
            continue
        if not box or box["width"] < _MIN_FRAME_SIZE or box["height"] < _MIN_FRAME_SIZE:
            continue
        try:
            data = await asyncio.wait_for(frame.evaluate(EXTRACT_JS), timeout=_FRAME_EVAL_TIMEOUT_S)
        except Exception:
            continue
        extracted += 1
        dx, dy = box["x"], box["y"]
        # Sites shrink embeds with CSS transform: scale(…) — bounding_box() is the RENDERED box but
        # in-frame coords are unscaled (frame innerWidth stays at layout size), so map through the
        # ratio. Unscaled frames give ratio 1.0. (quashbugs.com renders its HubSpot form at ~0.85;
        # without this, clicks landed ~40px off and focused the wrong field.)
        fw, fh = data["viewport_width"], data["viewport_height"]
        sx = box["width"] / fw if fw else 1.0
        sy = box["height"] / fh if fh else 1.0
        for e in data["elements"]:
            e["x"] = e["x"] * sx + dx
            e["y"] = e["y"] * sy + dy
            e["width"] *= sx
            e["height"] *= sy
            # Keep the frame-local verdict (an element scrolled out INSIDE the iframe is clipped and
            # unreachable at these coords) AND require the offset box to intersect the top viewport.
            e["in_viewport"] = bool(e["in_viewport"]) and (
                e["x"] + e["width"] > 0 and e["y"] + e["height"] > 0
                and e["x"] < meta.viewport_width and e["y"] < meta.viewport_height
            )
            out.append(RawElement(**e))
    return out


async def extract(page, *, retries: int = 3) -> tuple[list[RawElement], PageMeta]:
    """Run the DOM funnel over the main frame + every real-sized child iframe. Resilient to
    navigations (e.g. Enter submits a search → the page navigates mid-evaluate): on a destroyed
    context, wait for the new page to load and retry."""
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
        raw.extend(await _extract_child_frames(page, meta))
        return raw, meta
    raise last_exc if last_exc else RuntimeError("extract failed")
