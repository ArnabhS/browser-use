from __future__ import annotations

import asyncio
import base64
import logging
from urllib.parse import urlparse

from browser_agent_contracts import ActionCall, ActionResult, Observation, Tab
from playwright.async_api import Browser, Page, TimeoutError as PWTimeout, async_playwright

from app.browser.screencast import OnFrame, ScreencastStreamer
from app.browser.select_support import SELECT_JS, select_result
from app.browser.som_overlay import render_som
from app.browser.tab_registry import TabRegistry
from app.observation.extract import LISTENER_TAG_JS, extract, probe_dom
from app.observation.funnel.pipeline import run_funnel
from app.observation.page_query import (
    FIND_JS,
    SEARCH_JS,
    find_args,
    format_find,
    format_search,
    search_args,
)

logger = logging.getLogger(__name__)


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


_TARGET_BLANK_JS = """
([cx, cy]) => {
  let el = document.elementFromPoint(cx, cy);
  const a = el && (el.tagName === 'A' ? el : el.closest('a'));
  return !!(a && a.target === '_blank');
}
"""


def _navigable_href(href: str | None, current_url: str) -> str | None:
    """A hyperlink worth following as a click fallback: an http(s) target that is a different page
    than where we are (ignoring the #fragment). Rejects javascript:/mailto:/tel:, empty hrefs, and
    in-page anchors — those aren't navigations, so following them would be wrong."""
    if not href:
        return None
    low = href.lower()
    if not (low.startswith("http://") or low.startswith("https://")):
        return None
    if href.split("#", 1)[0] == current_url.split("#", 1)[0]:
        return None
    return href

# Real viewport size — visualViewport is correct on retina / CDP-attach where Playwright's
# page.viewport_size can be None. Falls back to innerWidth/Height.
_VIEWPORT_JS = (
    "() => [ (window.visualViewport && window.visualViewport.width) || window.innerWidth,"
    " (window.visualViewport && window.visualViewport.height) || window.innerHeight ]"
)


# Stealth: strip the obvious automation tells so bot-walls (PerimeterX/DataDome) serve the real
# page. The LOAD-BEARING lever is running HEADFUL — verified: from the same residential IP, headful
# loads real Skyscanner (543 elements) while headless gets the PerimeterX captcha (3 elements),
# because the deciding signal is the headless RENDERING fingerprint, not the CDP layer (Playwright
# sends Runtime.enable in both modes, yet headful passes). On the server we run headful under xvfb
# (see Dockerfile). These args/JS are cheap defense-in-depth on top of that.
_STEALTH_ARGS = ["--disable-blink-features=AutomationControlled"]
_STEALTH_IGNORE_DEFAULT_ARGS = ["--enable-automation"]
_STEALTH_JS = (
    "(() => {"
    "  try { Object.defineProperty(navigator, 'webdriver', { get: () => undefined }); } catch (e) {}"
    "  try { if (!window.chrome) { window.chrome = { runtime: {} }; } } catch (e) {}"
    "  try { if (!navigator.languages || !navigator.languages.length) {"
    "    Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en'] }); } } catch (e) {}"
    "})();"
)


class LocalCDPSession:
    """BrowserSession over a local Chromium (Playwright). Real eyes + trusted hands. Runs headful by
    default — see settings.cdp_headless — because headless is what most bot-walls detect."""

    def __init__(
        self,
        *,
        headless: bool = True,
        draw_som_overlay: bool = False,
        connect_url: str | None = None,
        funnel_debug: bool = False,
        funnel_focus: str = "",
        start_url: str = "",
        locale: str = "",
        timezone: str = "",
        geolocation: tuple[float, float] | None = None,
        proxy: str = "",
        stealth: bool = True,
    ) -> None:
        self._headless = headless
        self._stealth = stealth
        self._draw_overlay = draw_som_overlay
        # Home page the session opens on (empty = leave the blank tab). Production passes Google
        # from settings; kept empty by default so tests start hermetically on about:blank.
        self._start_url = start_url
        # Locale/timezone/geolocation the launched context presents. Empty by default (tests get
        # the host defaults); production passes India from settings. See _context_kwargs.
        self._locale = locale
        self._timezone = timezone
        self._geolocation = geolocation
        # Proxy URL (empty = direct). The only lever that changes the IP sites geolocate by.
        self._proxy = proxy
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
        self._dpr: float | None = None  # cached device pixel ratio for server-side SoM compositing
        # Live view: a best-effort CDP screencast of the active page, pushed out through on_frame
        # (the composition root wires it to the event emitter). Idle until start_stream().
        self.on_frame: OnFrame | None = None
        self._streamer = ScreencastStreamer()
        self._streaming = False
        self._stream_page: Page | None = None

    def _proxy_option(self) -> dict | None:
        """Parse the configured proxy URL into Playwright's proxy option (server + optional creds).
        Returns None when no proxy is set. Playwright wants credentials in separate fields, not
        embedded in the server URL."""
        raw = self._proxy.strip()
        if not raw:
            return None
        u = urlparse(raw)
        if not u.hostname:
            return None
        server = f"{u.scheme or 'http'}://{u.hostname}"
        if u.port:
            server += f":{u.port}"
        opt: dict = {"server": server}
        if u.username:
            opt["username"] = u.username
        if u.password:
            opt["password"] = u.password
        return opt

    def _context_kwargs(self) -> dict:
        """new_context() options for locale/timezone/geolocation, so pages see a consistent region
        instead of the datacenter's default. This shapes navigator.language, the Intl timezone, and
        the JS Geolocation API — it does NOT change the outbound IP (IP-based geo needs a proxy)."""
        kw: dict = {}
        if self._locale:
            kw["locale"] = self._locale
        if self._timezone:
            kw["timezone_id"] = self._timezone
        if self._geolocation:
            lat, lng = self._geolocation
            kw["geolocation"] = {"latitude": lat, "longitude": lng}
            kw["permissions"] = ["geolocation"]  # grant so getCurrentPosition returns it, no prompt
        return kw

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
            launch_kwargs: dict = {"headless": self._headless}
            proxy = self._proxy_option()
            if proxy:
                # Launch-level proxy is the reliable path for Chromium (used per-request, so an
                # unreachable proxy only bites on navigation, not at launch).
                launch_kwargs["proxy"] = proxy
            if self._stealth:
                launch_kwargs["args"] = _STEALTH_ARGS
                launch_kwargs["ignore_default_args"] = _STEALTH_IGNORE_DEFAULT_ARGS
            self._browser = await self._pw.chromium.launch(**launch_kwargs)
            ctx = await self._browser.new_context(**self._context_kwargs())
            if self._stealth:
                await ctx.add_init_script(_STEALTH_JS)  # runs before page scripts, in every frame
            self._page = await ctx.new_page()
        if self._start_url:
            # Best-effort home page: a failed/slow load must never stop the session from starting.
            try:
                await self._page.goto(self._start_url, wait_until="domcontentloaded", timeout=15000)
            except Exception as exc:
                logger.warning("start_url navigation to %s failed: %s", self._start_url, exc)
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
        await self._tag_listeners()
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
        # Capture a CLEAN frame — never inject the marks into the live DOM (that flashed the boxes in
        # the user's real browser and cost two extra JS round-trips). The Set-of-Marks are drawn onto
        # the image server-side instead, so the model still gets a marked screenshot (as JPEG) while
        # the page stays untouched.
        raw = await self._safe_screenshot()
        if raw and self._draw_overlay and self.index_boxes:
            try:
                raw = render_som(raw, self.index_boxes, await self._device_pixel_ratio())
            except Exception as e:  # compositing must never break observe
                logger.warning("SoM compositing failed (%s) — sending clean frame", e)
        self.latest_screenshot = raw
        return observation

    async def _tag_listeners(self) -> None:
        """Best-effort: flag elements carrying a real click/pointer listener (CDP getEventListeners,
        a DevTools-only API) into a WeakSet on window, which the page-context EXTRACT_JS then reads.
        Runs in the page's main world so the two evals share `window`. Never fatal."""
        try:
            cdp = await self._cdp_session()
            await cdp.send("Runtime.evaluate",
                           {"expression": LISTENER_TAG_JS, "includeCommandLineAPI": True, "returnByValue": True})
        except Exception:
            pass

    async def _device_pixel_ratio(self) -> float:
        """CDP captures at the device pixel ratio, but SoM boxes are in CSS px — this scales them to
        match. Cached: DPR is effectively constant for a session."""
        if self._dpr is None:
            try:
                self._dpr = float(await self.page.evaluate("() => window.devicePixelRatio")) or 1.0
            except Exception:
                self._dpr = 1.0
        return self._dpr

    _SCREENSHOT_TIMEOUT = 3.0

    async def _safe_screenshot(self) -> bytes | None:
        """Best-effort viewport screenshot for the vision model / live view — must never crash or
        stall the run. Captured via CDP Page.captureScreenshot, which grabs the frame immediately;
        Playwright's page.screenshot() instead blocks on fonts + paint-stability and hangs on
        animation-heavy sites (metacritic timed out every turn, starving the task). Keeps the
        previous frame on any failure."""
        try:
            cdp = await self._cdp_session()
            res = await asyncio.wait_for(
                cdp.send("Page.captureScreenshot", {"format": "png"}), timeout=self._SCREENSHOT_TIMEOUT
            )
            return base64.b64decode(res["data"])
        except Exception as e:
            # A hung capture blocks every command queued behind it on this CDP session — drop the
            # session so the next screenshot starts fresh instead of inheriting the stall (else one
            # slow page cascades into every later screenshot timing out).
            self._cdp = None
            logger.warning("screenshot failed (%s) — keeping previous frame", e or type(e).__name__)
            return self.latest_screenshot

    async def navigate(self, url: str) -> ActionResult:
        await self.page.goto(url)
        await self._settle()
        return ActionResult(success=True, reason=f"navigated to {url}")

    _ACTION_TIMEOUT = {"navigate": 30.0, "click": 10.0, "long_press": 15.0, "type": 10.0, "scroll": 5.0,
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
            url_before = self.page.url
            # Only a link that opens a new window is worth polling for after the click — check first
            # so a plain click doesn't pay the tab-wait (see _adopt_new_tab).
            expect_tab = name == "click" and bool(await self.page.evaluate(_TARGET_BLANK_JS, [cx, cy]))
            await self.page.mouse.click(cx, cy)
            if name == "type":
                await self.page.keyboard.type(str(args.get("text", "")))
            await self._settle()
            # Only a click can open a new tab; typing into a field never does — skip the wait.
            followed = await self._adopt_new_tab(before, expect_tab=expect_tab) if name == "click" else False
            tab = " (followed new tab)" if followed else ""
            # Click-doesn't-navigate fallback: some links (search-result cards, JS-routed anchors
            # that preventDefault) swallow a trusted click and never move the page, so the agent
            # re-clicks the same dead index until the loop guard trips. If the click landed on a
            # real hyperlink and nothing changed, follow its href directly.
            if name == "click" and not followed and self.page.url == url_before:
                href = _navigable_href(await self.page.evaluate(_HREF_AT_JS, [cx, cy]), url_before)
                if href:
                    try:
                        await self.page.goto(href, wait_until="domcontentloaded")
                        await self._settle()
                        tab = " (via link href)"
                    except Exception:  # bad/blocked href — leave the page as-is, agent will retry
                        pass
            return ActionResult(success=True, reason=f"{name} at [{args['index']}]{tab}")
        if name == "long_press":
            geo = self.index_map.get(int(args["index"]))
            if geo is None:
                return ActionResult(success=False, reason=f"stale index {args.get('index')}")
            cx, cy = geo
            duration = min(max(int(args.get("duration_ms", 800)), 0), 5000) / 1000
            before = set(self.page.context.pages)
            await self.page.mouse.move(cx, cy)
            await self.page.mouse.down()  # press and HOLD in place — trusted, isTrusted:true
            await asyncio.sleep(duration)
            await self.page.mouse.up()
            await self._settle()
            tab = " (followed new tab)" if await self._adopt_new_tab(before, expect_tab=False) else ""
            return ActionResult(
                success=True, reason=f"long-pressed [{args['index']}] for {int(duration * 1000)}ms{tab}"
            )
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
        if name == "search_page":
            res = await self.page.evaluate(SEARCH_JS, search_args(args))
            return ActionResult(success=not (res or {}).get("error"), reason=format_search(res))
        if name == "find_elements":
            res = await self.page.evaluate(FIND_JS, find_args(args))
            return ActionResult(success=not (res or {}).get("error"), reason=format_find(res))
        if name == "press_key":
            before = set(self.page.context.pages)
            await self.page.keyboard.press(str(args["key"]))
            await self._settle()
            tab = " (followed new tab)" if await self._adopt_new_tab(before, expect_tab=False) else ""
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
            res = await self.page.evaluate(SELECT_JS, [cx, cy, str(args["value"])])
            await self._settle()
            return select_result(res, args["value"])
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

    async def _adopt_new_tab(self, before: set, *, expect_tab: bool = True) -> bool:
        """If the last action opened a new tab (product/search result in a new window, via
        target=_blank or window.open), make it the active page so the next observation reflects
        what the user would now be looking at — instead of the unchanged original tab.

        `expect_tab` gates the poll: most clicks open no tab, and polling 3s on every one was a flat
        per-click tax (profiled 3.03s). When we don't expect a tab we only take the immediate check
        (catches a synchronous window.open) and return — any straggler is still picked up by the
        lazy `_follow_unseen_tab` on the very next observe."""
        ctx = self.page.context

        def _fresh():
            return [p for p in ctx.pages if p not in before and not p.is_closed()]

        opened = _fresh()
        # Only a link we know opens a new window is worth waiting on — a fresh cross-origin tab can
        # take a beat to register. Early-exits the instant it appears, so real tab-opens pay only
        # the open time, not the whole window.
        budget = 30 if expect_tab else 0  # 30×0.05s = 1.5s vs 0
        waited = 0
        while not opened and waited < budget:
            await asyncio.sleep(0.05)
            waited += 1
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
        # networkidle is a best-effort tail. Ad/analytics-heavy sites NEVER reach it, so this used
        # to burn the full 2s on every single action (a flat per-action tax). The load event above
        # is the real settle signal; keep only a short idle grace, and extract() retries if a
        # navigation is still in flight when we observe.
        try:
            await self.page.wait_for_load_state("networkidle", timeout=700)
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
