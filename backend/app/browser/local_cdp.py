from __future__ import annotations

import asyncio
import logging

from browser_agent_contracts import ActionCall, ActionResult, Observation, Tab
from playwright.async_api import Browser, Page, TimeoutError as PWTimeout, async_playwright

from app.browser.screencast import OnFrame, ScreencastStreamer
from app.browser.tab_registry import TabRegistry
from app.observation.extract import extract, probe_dom
from app.observation.funnel.pipeline import run_funnel

logger = logging.getLogger(__name__)

_SELECT_JS = """
([cx, cy, value]) => {
  const el = document.elementFromPoint(cx, cy);
  const sel = el && (el.tagName === 'SELECT' ? el : el.closest('select'));
  if (!sel) return false;
  let opt = [...sel.options].find(o => o.value === value || o.text === value);
  if (!opt) return false;
  sel.value = opt.value;
  sel.dispatchEvent(new Event('change', { bubbles: true }));
  return true;
}
"""

# Walk up from a viewport point to the nearest scrollable ancestor and scroll IT. Used both
# as the page-scroll fallback (point = viewport centre, tryWindow=true) and for index-targeted
# container scroll (point = the element, tryWindow=false so the window is left untouched).
_SCROLL_AT_JS = """
([cx, cy, dy, tryWindow]) => {
  if (tryWindow) {
    const y0 = window.scrollY;
    window.scrollBy(0, dy);
    if (Math.abs(window.scrollY - y0) > 1) return true;
  }
  let el = document.elementFromPoint(cx, cy);
  while (el && el !== document.documentElement && el !== document.body) {
    const s = getComputedStyle(el);
    if ((s.overflowY === 'auto' || s.overflowY === 'scroll') && (el.scrollHeight - el.clientHeight) > 1) {
      const t0 = el.scrollTop; el.scrollBy(0, dy); return Math.abs(el.scrollTop - t0) > 1;
    }
    el = el.parentElement;
  }
  return false;
}
"""

_HREF_AT_JS = """
([cx, cy]) => {
  let el = document.elementFromPoint(cx, cy);
  const a = el && (el.tagName === 'A' ? el : el.closest('a'));
  return a && a.href ? a.href : null;
}
"""

# Real viewport size — visualViewport is correct on retina / CDP-attach where Playwright's
# page.viewport_size can be None. Falls back to innerWidth/Height.
_VIEWPORT_JS = (
    "() => [ (window.visualViewport && window.visualViewport.width) || window.innerWidth,"
    " (window.visualViewport && window.visualViewport.height) || window.innerHeight ]"
)

_SOM_OVERLAY_JS = """
(boxes) => {
  const old = document.getElementById('__som_overlay__'); if (old) old.remove();
  const c = document.createElement('div');
  c.id = '__som_overlay__';
  c.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;pointer-events:none;z-index:2147483647';
  const colors = ['#E6194B','#3CB44B','#4363D8','#F58231','#911EB4','#008080','#F032E6','#BFEF45'];
  for (const b of boxes) {
    const idx=b[0], x=b[1], y=b[2], w=b[3], h=b[4], col=colors[idx % colors.length];
    const box = document.createElement('div');
    box.style.cssText = `position:absolute;left:${x}px;top:${y}px;width:${w}px;height:${h}px;border:2px solid ${col};box-sizing:border-box`;
    const lab = document.createElement('div');
    lab.textContent = idx;
    lab.style.cssText = `position:absolute;left:${x}px;top:${Math.max(0,y-14)}px;background:${col};color:#fff;font:bold 11px monospace;padding:0 3px;line-height:14px`;
    c.appendChild(box); c.appendChild(lab);
  }
  document.body.appendChild(c);
}
"""


class LocalCDPSession:
    """BrowserSession over a local headless Chromium (Playwright). Real eyes + trusted hands."""

    def __init__(
        self,
        *,
        headless: bool = True,
        draw_som_overlay: bool = False,
        connect_url: str | None = None,
        funnel_debug: bool = False,
        funnel_focus: str = "",
    ) -> None:
        self._headless = headless
        self._draw_overlay = draw_som_overlay
        # Diagnostics: when on, each observe() logs a per-stage funnel trace + a raw-DOM probe
        # for `funnel_focus`, so a "can see it, can't click it" element can be traced to the
        # exact stage that drops it (or shown to be never extracted at all).
        self._funnel_debug = funnel_debug
        self._funnel_focus = funnel_focus
        # If set (e.g. "http://localhost:9222"), attach to the user's already-running Chrome
        # over CDP instead of launching a fresh Chromium — drives their real profile/logins.
        self._connect_url = connect_url
        self._pw = None
        self._browser: Browser | None = None
        self._page: Page | None = None
        self.index_map: dict[int, tuple[float, float]] = {}
        self.index_boxes: dict[int, tuple[float, float, float, float]] = {}
        self.latest_screenshot: bytes | None = None
        self._shot_counter = 0
        self._seen_pages: set = set()  # tabs we've accounted for (for lazy new-tab follow)
        self._registry = TabRegistry()  # stable per-session tab ids the agent reasons about
        self._cdp = None               # cached CDP session for the active page (scroll gestures)
        self._cdp_page: Page | None = None
        # Live view: a best-effort CDP screencast of the active page, pushed out through on_frame
        # (the composition root wires it to the event emitter). Idle until start_stream().
        self.on_frame: OnFrame | None = None
        self._streamer = ScreencastStreamer()
        self._streaming = False
        self._stream_page: Page | None = None

    async def start(self) -> None:
        self._pw = await async_playwright().start()
        if self._connect_url:
            # Attach to the user's running Chrome (started with --remote-debugging-port=PORT).
            # Chrome's debug port binds IPv4 (127.0.0.1); "localhost" can resolve to IPv6 (::1)
            # and be refused, so force IPv4. Reuse their context (logins), open a fresh tab.
            url = self._connect_url.replace("://localhost", "://127.0.0.1")
            try:
                self._browser = await self._pw.chromium.connect_over_cdp(url)
            except Exception as exc:
                await self._pw.stop()
                self._pw = None
                raise RuntimeError(
                    f"Could not attach to Chrome at {url}. Start Chrome with "
                    '--remote-debugging-port=9222 --user-data-dir="$HOME/chrome-agent" and keep it '
                    f"open (verify: curl {url}/json/version). [{type(exc).__name__}: {exc}]"
                ) from exc
            ctx = self._browser.contexts[0] if self._browser.contexts else await self._browser.new_context()
            self._page = await ctx.new_page()
        else:
            self._browser = await self._pw.chromium.launch(headless=self._headless)
            ctx = await self._browser.new_context()
            self._page = await ctx.new_page()
        self._registry.register(self._page)  # tab 0
        self._seen_pages = {self._page}

    async def stop(self) -> None:
        # Attached to the user's real browser: close only our tab, never their browser.
        if self._connect_url and self._page is not None:
            try:
                await self._page.close()
            except Exception:
                pass
        if self._browser is not None:
            # For connect_over_cdp this disconnects Playwright without killing their Chrome.
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("call start() first")
        return self._page

    def _follow_unseen_tab(self) -> None:
        """Lazy safety net: if a tab opened since we last looked (e.g. a click's new tab that
        registered after the action's wait window), follow the newest one before observing."""
        if self._page is None:
            return
        pages = [p for p in self._page.context.pages if not p.is_closed()]
        unseen = [p for p in pages if p not in self._seen_pages]
        self._seen_pages = set(pages)
        if unseen and unseen[-1] is not self._page:
            self._page = unseen[-1]

    async def observe(self, *, include_som: bool = True) -> Observation:
        self._follow_unseen_tab()
        await self._ensure_stream_on_active_page()
        raw, meta = await extract(self.page)
        self._shot_counter += 1
        ref = f"shot-{self._shot_counter}"
        focus = self._funnel_focus if self._funnel_debug else None
        observation, self.index_map, self.index_boxes = run_funnel(
            raw, meta, screenshot_ref=ref, debug_focus=focus
        )
        observation.tabs = await self._tab_snapshot()
        if focus:
            await self._log_dom_probe(focus, meta.url)
        if self._draw_overlay and self.index_boxes:
            await self.page.evaluate(_SOM_OVERLAY_JS, [[i, *b] for i, b in self.index_boxes.items()])
            self.latest_screenshot = await self.page.screenshot()
            await self.page.evaluate("() => { const o = document.getElementById('__som_overlay__'); if (o) o.remove(); }")
        else:
            self.latest_screenshot = await self.page.screenshot()
        return observation

    async def navigate(self, url: str) -> ActionResult:
        await self.page.goto(url)
        await self._settle()
        return ActionResult(success=True, reason=f"navigated to {url}")

    _ACTION_TIMEOUT = {"navigate": 30.0, "click": 10.0, "type": 10.0, "scroll": 5.0,
                       "wait_for": 30.0, "extract": 15.0, "press_key": 5.0, "clear": 10.0,
                       "select_option": 10.0, "new_tab": 30.0, "switch_tab": 5.0, "close_tab": 5.0,
                       "observe_tab": 5.0, "open_in_new_tab": 30.0}

    async def act(self, call: ActionCall) -> ActionResult:
        timeout = self._ACTION_TIMEOUT.get(call.name, 10.0)
        try:
            return await asyncio.wait_for(self._dispatch(call), timeout=timeout)
        except asyncio.TimeoutError:
            return ActionResult(success=False, reason=f"{call.name} timed out after {timeout}s",
                                errorCode="ACTION_TIMEOUT")
        except Exception as e:  # Playwright errors, bad args, etc. — fail closed, never crash the run
            return ActionResult(success=False, reason=f"{call.name} failed: {e}", errorCode="ACTION_ERROR")

    async def _dispatch(self, call: ActionCall) -> ActionResult:
        name, args = call.name, call.args
        if name == "navigate":
            return await self.navigate(args["url"])
        if name in {"click", "type"}:
            geo = self.index_map.get(int(args["index"]))
            if geo is None:
                return ActionResult(success=False, reason=f"stale index {args.get('index')}")
            cx, cy = geo
            before = set(self.page.context.pages)
            await self.page.mouse.click(cx, cy)
            if name == "type":
                await self.page.keyboard.type(str(args.get("text", "")))
            await self._settle()
            # Only a click can open a new tab; typing into a field never does — skip the wait.
            followed = await self._adopt_new_tab(before) if name == "click" else False
            tab = " (followed new tab)" if followed else ""
            return ActionResult(success=True, reason=f"{name} at [{args['index']}]{tab}")
        if name == "scroll":
            direction = args.get("direction", "down")
            steps = int(args.get("amount", 1))
            vw, vh = await self._viewport_metrics()
            dy = int(vh * steps) * (-1 if direction == "up" else 1)
            index = args.get("index")
            if index is not None:
                geo = self.index_map.get(int(index))
                if geo is None:
                    return ActionResult(success=False, reason=f"stale index {index}")
                cx, cy = geo
                moved = bool(await self.page.evaluate(_SCROLL_AT_JS, [cx, cy, dy, False]))
            else:
                moved = await self._scroll_page(dy, vw // 2, vh // 2)
            await self._settle()
            if moved:
                return ActionResult(success=True, reason=f"scrolled {direction}")
            return ActionResult(success=False, reason=f"could not scroll {direction} — already at the page edge")
        if name == "wait_for":
            await asyncio.sleep(min(float(args.get("seconds", 1.0)), 10.0))
            return ActionResult(success=True, reason="waited")
        if name == "extract":
            text = (await self.page.inner_text("body"))[:4000]
            return ActionResult(success=True, reason=text)
        if name == "press_key":
            before = set(self.page.context.pages)
            await self.page.keyboard.press(str(args["key"]))
            await self._settle()
            tab = " (followed new tab)" if await self._adopt_new_tab(before) else ""
            return ActionResult(success=True, reason=f"pressed {args['key']}{tab}")
        if name == "clear":
            geo = self.index_map.get(int(args["index"]))
            if geo is None:
                return ActionResult(success=False, reason=f"stale index {args.get('index')}")
            cx, cy = geo
            await self.page.mouse.click(cx, cy, click_count=3)  # select all
            await self.page.keyboard.press("Delete")
            await self._settle()
            return ActionResult(success=True, reason=f"cleared [{args['index']}]")
        if name == "select_option":
            geo = self.index_map.get(int(args["index"]))
            if geo is None:
                return ActionResult(success=False, reason=f"stale index {args.get('index')}")
            cx, cy = geo
            ok = await self.page.evaluate(_SELECT_JS, [cx, cy, str(args["value"])])
            await self._settle()
            return ActionResult(success=bool(ok),
                                reason=f"selected {args['value']}" if ok else "option/select not found")
        if name == "new_tab":
            page = await self.page.context.new_page()
            await page.goto(args["url"])
            self._page = page
            live = [p for p in page.context.pages if not p.is_closed()]
            self._registry.sync(live)
            self._seen_pages = set(live)
            await self._settle()
            return ActionResult(success=True, reason=f"opened {args['url']}")
        if name == "open_in_new_tab":
            geo = self.index_map.get(int(args["index"]))
            if geo is None:
                return ActionResult(success=False, reason=f"stale index {args.get('index')}")
            cx, cy = geo
            href = await self.page.evaluate(_HREF_AT_JS, [cx, cy])
            if not href:
                return ActionResult(success=False, reason="no link at that element to open in a new tab")
            page = await self.page.context.new_page()
            await page.goto(href)
            # Background it: keep focus on the current tab and mark every live tab "seen" so the
            # lazy auto-follow in observe() does NOT switch to the tab we just spawned.
            live = [p for p in self.page.context.pages if not p.is_closed()]
            self._registry.sync(live)
            self._seen_pages = set(live)
            return ActionResult(success=True,
                                reason=f"opened link in new tab {self._registry.id_of(page)} (still on current tab)")
        if name in {"switch_tab", "close_tab", "observe_tab"}:
            pages = [p for p in self.page.context.pages if not p.is_closed()]
            self._registry.sync(pages)
            target = self._registry.page_for(int(args["target_id"]), pages)
            if target is None:
                return ActionResult(success=False, reason=f"no tab {args['target_id']}")
            if name == "observe_tab":
                try:
                    title = await target.title()
                except Exception:
                    title = ""
                return ActionResult(success=True, reason=f'tab {args["target_id"]}: "{title}" — {target.url}')
            if name == "switch_tab":
                self._page = target
                self._seen_pages = set(pages)  # a deliberate switch must not be overridden by auto-follow
                return ActionResult(success=True, reason=f"switched to tab {args['target_id']}")
            # close_tab
            await target.close()
            remaining = [p for p in self.page.context.pages if not p.is_closed()]
            if target is self._page:
                self._page = remaining[-1] if remaining else None
            self._seen_pages = set(remaining)
            return ActionResult(success=True, reason=f"closed tab {args['target_id']}")
        return ActionResult(success=False, reason=f"unsupported action {name}")

    async def _adopt_new_tab(self, before: set) -> bool:
        """If the last action opened a new tab (product/search result in a new window, via
        target=_blank or window.open), make it the active page so the next observation reflects
        what the user would now be looking at — instead of the unchanged original tab."""
        ctx = self.page.context

        def _fresh():
            return [p for p in ctx.pages if p not in before and not p.is_closed()]

        opened = _fresh()
        # The tab can take ~1–3s to register (it's a fresh navigation) — poll the live page
        # list (not an event, so we can't miss one fired in the gap). Early-exits the instant a
        # tab appears, so tab-opening clicks pay only the real open time, not the whole window.
        for _ in range(30):
            if opened:
                break
            await asyncio.sleep(0.1)
            opened = _fresh()
        if not opened:
            return False
        self._page = opened[-1]  # follow the newest tab the action spawned
        try:
            await self._page.wait_for_load_state("load", timeout=8000)
        except Exception:
            pass
        return True

    async def _settle(self, bound: float = 5.0) -> None:
        # After an action that may navigate (Enter submits a form, a link click), wait for the
        # new page to finish loading first, then briefly for the network to quiet. Heavy sites
        # never reach networkidle, so that wait is short and best-effort; extract() retries if a
        # navigation is still in flight when we observe.
        try:
            await self.page.wait_for_load_state("load", timeout=bound * 1000)
        except Exception:
            pass
        try:
            await self.page.wait_for_load_state("networkidle", timeout=2000)
        except Exception:
            pass

    async def tabs(self) -> list[Tab]:
        return await self._tab_snapshot()

    async def _tab_snapshot(self) -> list[Tab]:
        pages = [p for p in self.page.context.pages if not p.is_closed()]
        self._registry.sync(pages)
        out: list[Tab] = []
        for p in pages:
            tid = self._registry.id_of(p)
            if tid is None:
                continue
            try:
                title = await p.title()
            except Exception:
                title = ""
            out.append(Tab(id=tid, title=title, url=p.url, active=(p is self._page)))
        return sorted(out, key=lambda t: t.id)

    async def _cdp_session(self):
        if self._cdp is None or self._cdp_page is not self._page:
            self._cdp = await self.page.context.new_cdp_session(self.page)
            self._cdp_page = self._page
        return self._cdp

    async def start_stream(self) -> None:
        """Begin a live screencast of the active page, pushed out through on_frame. Best-effort:
        if on_frame isn't wired or the screencast can't start, the run proceeds without a live view."""
        if self.on_frame is None:
            return
        self._streaming = True
        await self._point_stream()

    async def stop_stream(self) -> None:
        self._streaming = False
        try:
            await self._streamer.stop()
        except Exception:
            pass
        self._stream_page = None

    def _active_url(self) -> str:
        return self._page.url if self._page is not None else ""

    async def _point_stream(self) -> None:
        """(Re)bind the screencast to the current active page — its own CDP session, separate
        from the scroll-gesture one."""
        if not self._streaming or self.on_frame is None or self._page is None:
            return
        try:
            cdp = await self.page.context.new_cdp_session(self.page)
            await self._streamer.start(cdp, on_frame=self.on_frame, url_getter=self._active_url)
            self._stream_page = self._page
        except Exception as exc:
            logger.warning("screencast re-point failed: %s", exc)

    async def _ensure_stream_on_active_page(self) -> None:
        """Follow the agent when it switches/opens tabs: re-point the stream if the active page
        changed since we last bound it (checked each observe, right after tab auto-follow)."""
        if self._streaming and self._stream_page is not self._page:
            await self._point_stream()

    async def _log_dom_probe(self, focus: str, url: str) -> None:
        probe = await probe_dom(self.page, focus)
        if not probe:
            logger.warning("[probe] no DOM element on %s contains %r", url, focus)
            return
        lines = [
            f"    #{i}: {p['tag']}<{p['role']}> \"{p['text']}\" would_extract={p['would_extract']} "
            f"pos={p['position']} cursor={p['cursor']} vis={p['visibility']}/{p['display']}/op{p['opacity']} "
            f"rect={p['rect']} hit={p['hit']} self_or_child={p['hit_is_self_or_child']}"
            for i, p in enumerate(probe)
        ]
        logger.warning("[probe] DOM nodes containing %r on %s\n%s", focus, url, "\n".join(lines))

    async def _viewport_metrics(self) -> tuple[int, int]:
        try:
            vw, vh = await self.page.evaluate(_VIEWPORT_JS)
            return int(vw) or 1280, int(vh) or 720
        except Exception:
            return 1280, 720

    async def _scroll_page(self, dy: int, cx: int, cy: int) -> bool:
        y0 = await self.page.evaluate("() => window.scrollY")
        # Momentum gesture first — infinite-scroll feeds (Flipkart/Myntra PLP) watch for the
        # wheel-momentum signal to lazy-load; an instant scrollBy gets ignored by them.
        try:
            cdp = await self._cdp_session()
            await cdp.send("Input.synthesizeScrollGesture",
                           {"x": cx, "y": cy, "xDistance": 0, "yDistance": -dy, "speed": 2500})
        except Exception:
            pass
        if abs((await self.page.evaluate("() => window.scrollY")) - y0) > 1:
            return True
        # Gesture was a no-op (non-feed page, or swallowed by a fixed header): fall back to a
        # direct window scroll, then the scroll container under the viewport centre.
        return bool(await self.page.evaluate(_SCROLL_AT_JS, [cx, cy, dy, True]))
