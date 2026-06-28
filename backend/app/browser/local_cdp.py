from __future__ import annotations

import asyncio

from browser_agent_contracts import ActionCall, ActionResult, Observation
from playwright.async_api import Browser, Page, TimeoutError as PWTimeout, async_playwright

from app.observation.extract import extract
from app.observation.funnel.pipeline import run_funnel
from app.telemetry.records import TabInfo


class LocalCDPSession:
    """BrowserSession over a local headless Chromium (Playwright). Real eyes + trusted hands."""

    def __init__(self, *, headless: bool = True) -> None:
        self._headless = headless
        self._pw = None
        self._browser: Browser | None = None
        self._page: Page | None = None
        self.index_map: dict[int, tuple[float, float]] = {}
        self.latest_screenshot: bytes | None = None
        self._shot_counter = 0

    async def start(self) -> None:
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self._headless)
        context = await self._browser.new_context()
        self._page = await context.new_page()

    async def stop(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()

    @property
    def page(self) -> Page:
        assert self._page is not None, "call start() first"
        return self._page

    async def observe(self, *, include_som: bool = True) -> Observation:
        raw, meta = await extract(self.page)
        self.latest_screenshot = await self.page.screenshot()
        self._shot_counter += 1
        ref = f"shot-{self._shot_counter}"
        observation, self.index_map = run_funnel(raw, meta, screenshot_ref=ref)
        return observation

    async def navigate(self, url: str) -> ActionResult:
        await self.page.goto(url)
        return ActionResult(success=True, reason=f"navigated to {url}")

    _ACTION_TIMEOUT = {"navigate": 30.0, "click": 10.0, "type": 10.0, "scroll": 5.0,
                       "wait_for": 30.0, "extract": 15.0}

    async def act(self, call: ActionCall) -> ActionResult:
        timeout = self._ACTION_TIMEOUT.get(call.name, 10.0)
        try:
            return await asyncio.wait_for(self._dispatch(call), timeout=timeout)
        except asyncio.TimeoutError:
            return ActionResult(success=False, reason=f"{call.name} timed out after {timeout}s",
                                errorCode="ACTION_TIMEOUT")

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
        return ActionResult(success=False, reason=f"unsupported action {name}")

    async def _settle(self, bound: float = 3.0) -> None:
        try:
            await self.page.wait_for_load_state("networkidle", timeout=bound * 1000)
        except PWTimeout:
            pass

    async def tabs(self) -> list[TabInfo]:
        pages = self.page.context.pages
        return [
            TabInfo(target_id=str(i), url=p.url, title=await p.title(), active=(p is self._page))
            for i, p in enumerate(pages)
        ]
