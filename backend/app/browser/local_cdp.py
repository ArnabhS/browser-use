from __future__ import annotations

from browser_agent_contracts import ActionCall, ActionResult, Observation
from playwright.async_api import Browser, Page, async_playwright

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

    async def act(self, call: ActionCall) -> ActionResult:  # implemented in Task 7
        raise NotImplementedError

    async def tabs(self) -> list[TabInfo]:  # implemented in Task 7
        raise NotImplementedError
