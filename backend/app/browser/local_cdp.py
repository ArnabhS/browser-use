from __future__ import annotations

import asyncio

from browser_agent_contracts import ActionCall, ActionResult, Observation
from playwright.async_api import Browser, Page, TimeoutError as PWTimeout, async_playwright

from app.observation.extract import extract
from app.observation.funnel.pipeline import run_funnel
from app.telemetry.records import TabInfo

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
    ) -> None:
        self._headless = headless
        self._draw_overlay = draw_som_overlay
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

    async def start(self) -> None:
        self._pw = await async_playwright().start()
        if self._connect_url:
            # Attach to the user's running Chrome (started with --remote-debugging-port=PORT).
            # Reuse their existing context (cookies/logins) and open a fresh tab there.
            self._browser = await self._pw.chromium.connect_over_cdp(self._connect_url)
            ctx = self._browser.contexts[0] if self._browser.contexts else await self._browser.new_context()
            self._page = await ctx.new_page()
        else:
            self._browser = await self._pw.chromium.launch(headless=self._headless)
            ctx = await self._browser.new_context()
            self._page = await ctx.new_page()

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

    async def observe(self, *, include_som: bool = True) -> Observation:
        raw, meta = await extract(self.page)
        self._shot_counter += 1
        ref = f"shot-{self._shot_counter}"
        observation, self.index_map, self.index_boxes = run_funnel(raw, meta, screenshot_ref=ref)
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
                       "select_option": 10.0, "new_tab": 30.0, "switch_tab": 5.0, "close_tab": 5.0}

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
            await self.page.mouse.click(cx, cy)
            if name == "type":
                await self.page.keyboard.type(str(args.get("text", "")))
            await self._settle()
            return ActionResult(success=True, reason=f"{name} at [{args['index']}]")
        if name == "scroll":
            dy = 600 * int(args.get("amount", 1)) * (-1 if args.get("direction") == "up" else 1)
            await self.page.mouse.wheel(0, dy)
            await self._settle()
            return ActionResult(success=True, reason=f"scrolled {args.get('direction', 'down')}")
        if name == "wait_for":
            await asyncio.sleep(min(float(args.get("seconds", 1.0)), 10.0))
            return ActionResult(success=True, reason="waited")
        if name == "extract":
            text = (await self.page.inner_text("body"))[:4000]
            return ActionResult(success=True, reason=text)
        if name == "press_key":
            await self.page.keyboard.press(str(args["key"]))
            await self._settle()
            return ActionResult(success=True, reason=f"pressed {args['key']}")
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
            await self._settle()
            return ActionResult(success=True, reason=f"opened {args['url']}")
        if name in {"switch_tab", "close_tab"}:
            pages = self.page.context.pages
            i = int(args["target_id"])
            if not (0 <= i < len(pages)):
                return ActionResult(success=False, reason=f"no tab {args['target_id']}")
            if name == "switch_tab":
                self._page = pages[i]
                return ActionResult(success=True, reason=f"switched to tab {i}")
            ctx = self.page.context
            await pages[i].close()
            self._page = ctx.pages[-1] if ctx.pages else None
            return ActionResult(success=True, reason=f"closed tab {i}")
        return ActionResult(success=False, reason=f"unsupported action {name}")

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

    async def tabs(self) -> list[TabInfo]:
        pages = self.page.context.pages
        return [
            TabInfo(target_id=str(i), url=p.url, title=await p.title(), active=(p is self._page))
            for i, p in enumerate(pages)
        ]
