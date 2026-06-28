# Phase B3 — Real Browser (LocalCDPSession + Observation Funnel) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the agent **real eyes and hands**: a `LocalCDPSession` that drives headless Chromium via Playwright and turns each page into the `Observation` contract through a Python **observation funnel**, then performs the agent's `ActionCall`s as **trusted input**. Swap the fake `BrowserSession` for it with zero graph changes; prove it on local HTML fixtures.

**Architecture:** `LocalCDPSession` (implements the B1 `BrowserSession` port) owns a Playwright `Browser`/`Page`. `observe()` injects a JS DOM-walker (`page.evaluate`) to extract candidate interactive elements with viewport geometry, runs the **funnel** (`VisibilityFilter → SoMIndexer → ReadingOrderFormatter`) to produce the numbered `Observation` + a hidden `index → (centerX, centerY)` map, and captures a screenshot. `act()` resolves the index to coordinates and performs trusted input via `page.mouse`/`page.keyboard` (Playwright dispatches these through CDP `Input.*`, so `isTrusted: true`). The funnel stages are pure-Python and unit-tested without a browser; the session is integration-tested against `page.set_content` fixtures.

**Tech Stack:** Playwright (async, Chromium — already installed via `playwright install chromium`), Pydantic v2, pytest/pytest-asyncio. (Playwright is already in `backend/pyproject.toml`.)

## Global Constraints

- Work in `backend/`; tests `cd backend && uv run pytest`. `asyncio_mode="auto"` is set.
- **Swap-in with zero graph changes**: `LocalCDPSession` satisfies the existing `BrowserSession` Protocol (`observe`/`act`/`navigate`/`tabs`) exactly. The graph, nodes, dispatcher, and `ActionCall`/`Observation` contracts are unchanged.
- **The raw DOM never leaves the funnel.** `observe()` returns only the `Observation` contract (numbered elements + screenshot ref + viewport + droppedCount) — **no coordinates, no raw HTML**. Coordinates live only in the session's hidden index→geometry map.
- **Indices are rebuilt every `observe()`** — never reused across turns.
- **Trusted input**: clicks/typing go through `page.mouse`/`page.keyboard` (CDP-backed, `isTrusted:true`). Never `element.click()` JS as the default.
- **No silent truncation**: when the element list exceeds the token budget, drop lowest-priority (off-screen) first and set `Observation.droppedCount` (+ a "N hidden" line). 
- **Per-action timeout walls**; on timeout return `ActionResult(success=False, reason=..., error_code="ACTION_TIMEOUT")`.
- **Settle before re-observe**: wait for the page to go quiet (bounded) after an action.
- YAGNI for B3: ship `Extract + VisibilityFilter + SoMIndexer + ReadingOrderFormatter` (a correct, usable funnel). `OcclusionCuller` + `WrapperCollapser` are deferred fast-follows (B3.1). Adaptive per-host settle is a fast-follow (fixed bound now).
- Reuse `browser_agent_contracts` (`Observation`, `Element`, `Viewport`, `ActionCall`, `ActionResult`), the B1 `BrowserSession` port, `TabInfo`.

### Shared spine (names every task must match)

```python
# app/observation/raw.py: RawElement(BaseModel): tag, role, name, value:str|None, x, y, width, height, visible:bool, in_viewport:bool
#                         PageMeta(BaseModel): url, title, viewport_width, viewport_height, scroll_x, scroll_y
# app/observation/funnel/visibility.py: VisibilityFilter.apply(raw: list[RawElement]) -> list[RawElement]
# app/observation/funnel/som.py: IndexedElement(RawElement + index:int, center_x:float, center_y:float)
#                                SoMIndexer.apply(raw: list[RawElement]) -> list[IndexedElement]
# app/observation/funnel/reading_order.py: ReadingOrderFormatter(max_elements:int=120)
#                                          .apply(indexed: list[IndexedElement]) -> tuple[list[Element], int]   # (elements, dropped)
# app/observation/funnel/pipeline.py: run_funnel(raw, meta, *, screenshot_ref) -> tuple[Observation, dict[int, tuple[float,float]]]
# app/observation/extract.py: EXTRACT_JS (str); async extract(page) -> tuple[list[RawElement], PageMeta]
# app/browser/local_cdp.py: LocalCDPSession(BrowserSession): async start()/stop(); observe/act/navigate/tabs;
#                           per-instance index_map: dict[int, tuple[float,float]]; latest_screenshot: bytes|None
```

## File Structure

```
backend/app/observation/
├─ raw.py                 # RawElement, PageMeta
├─ extract.py             # EXTRACT_JS + extract(page)
└─ funnel/
   ├─ __init__.py
   ├─ visibility.py       # VisibilityFilter
   ├─ som.py              # IndexedElement, SoMIndexer
   ├─ reading_order.py    # ReadingOrderFormatter
   └─ pipeline.py         # run_funnel → Observation + index_map
backend/app/browser/local_cdp.py   # LocalCDPSession
backend/app/config/{settings.py, container.py}  # browser_backend flag
backend/tests/observation/{test_visibility,test_som,test_reading_order,test_pipeline,test_extract_live,test_funnel_live}.py
backend/tests/browser/{test_local_cdp_observe,test_local_cdp_act}.py
backend/tests/agent/test_real_browser_e2e.py
```

---

### Task 1: Funnel data types + VisibilityFilter (pure Python)

**Files:** Create `backend/app/observation/raw.py`, `backend/app/observation/funnel/__init__.py`, `backend/app/observation/funnel/visibility.py`. Test: `backend/tests/observation/__init__.py`, `backend/tests/observation/test_visibility.py`

**Interfaces:** Produces `RawElement` + `PageMeta` (Pydantic), and `VisibilityFilter.apply(raw) -> list[RawElement]` dropping elements with `visible=False` or `width<=0`/`height<=0`.

- [ ] **Step 1: Write the failing test `backend/tests/observation/test_visibility.py`** (create `backend/tests/observation/__init__.py` empty first)

```python
from app.observation.raw import RawElement
from app.observation.funnel.visibility import VisibilityFilter


def _el(**kw):
    base = dict(tag="button", role="button", name="x", value=None,
                x=0, y=0, width=10, height=10, visible=True, in_viewport=True)
    base.update(kw)
    return RawElement(**base)


def test_visibility_drops_hidden_and_zero_size():
    raw = [_el(name="ok"), _el(name="hidden", visible=False), _el(name="zero", width=0)]
    kept = VisibilityFilter().apply(raw)
    assert [e.name for e in kept] == ["ok"]
```

- [ ] **Step 2: Run to verify it fails** — `cd backend && uv run pytest tests/observation/test_visibility.py -v` → FAIL (`No module named 'app.observation.raw'`).

- [ ] **Step 3: Create `backend/app/observation/raw.py`**

```python
from __future__ import annotations

from pydantic import BaseModel


class RawElement(BaseModel):
    tag: str
    role: str
    name: str = ""
    value: str | None = None
    x: float
    y: float
    width: float
    height: float
    visible: bool = True
    in_viewport: bool = True


class PageMeta(BaseModel):
    url: str
    title: str = ""
    viewport_width: int
    viewport_height: int
    scroll_x: int = 0
    scroll_y: int = 0
```

- [ ] **Step 4: Create `backend/app/observation/funnel/__init__.py`** (empty file).

- [ ] **Step 5: Create `backend/app/observation/funnel/visibility.py`**

```python
from __future__ import annotations

from app.observation.raw import RawElement


class VisibilityFilter:
    """Drop elements that are not visible or have zero area."""

    def apply(self, raw: list[RawElement]) -> list[RawElement]:
        return [e for e in raw if e.visible and e.width > 0 and e.height > 0]
```

- [ ] **Step 6: Run to verify it passes** — `cd backend && uv run pytest tests/observation/test_visibility.py -v` → 1 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/observation/raw.py backend/app/observation/funnel/__init__.py backend/app/observation/funnel/visibility.py backend/tests/observation
git commit -m "feat(observation): RawElement/PageMeta + VisibilityFilter funnel stage"
```

---

### Task 2: SoMIndexer (pure Python)

**Files:** Create `backend/app/observation/funnel/som.py`. Test: `backend/tests/observation/test_som.py`

**Interfaces:** Produces `IndexedElement` (a `RawElement` plus `index:int`, `center_x:float`, `center_y:float`) and `SoMIndexer.apply(raw) -> list[IndexedElement]` assigning indices `1..N` in input order and computing the box center.

- [ ] **Step 1: Write the failing test `backend/tests/observation/test_som.py`**

```python
from app.observation.raw import RawElement
from app.observation.funnel.som import SoMIndexer


def _el(x, y, w, h):
    return RawElement(tag="button", role="button", name="b", value=None,
                      x=x, y=y, width=w, height=h, visible=True, in_viewport=True)


def test_som_assigns_indices_and_centers():
    out = SoMIndexer().apply([_el(0, 0, 10, 20), _el(100, 50, 40, 40)])
    assert [e.index for e in out] == [1, 2]
    assert (out[0].center_x, out[0].center_y) == (5.0, 10.0)
    assert (out[1].center_x, out[1].center_y) == (120.0, 70.0)
```

- [ ] **Step 2: Run to verify it fails** — `cd backend && uv run pytest tests/observation/test_som.py -v` → FAIL.

- [ ] **Step 3: Create `backend/app/observation/funnel/som.py`**

```python
from __future__ import annotations

from app.observation.raw import RawElement


class IndexedElement(RawElement):
    index: int
    center_x: float
    center_y: float


class SoMIndexer:
    """Assign a small integer [N] to each element and compute its click center."""

    def apply(self, raw: list[RawElement]) -> list[IndexedElement]:
        out: list[IndexedElement] = []
        for i, e in enumerate(raw, start=1):
            out.append(
                IndexedElement(
                    **e.model_dump(),
                    index=i,
                    center_x=e.x + e.width / 2,
                    center_y=e.y + e.height / 2,
                )
            )
        return out
```

- [ ] **Step 4: Run to verify it passes** — `cd backend && uv run pytest tests/observation/test_som.py -v` → 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/observation/funnel/som.py backend/tests/observation/test_som.py
git commit -m "feat(observation): SoMIndexer funnel stage (indices + click centers)"
```

---

### Task 3: ReadingOrderFormatter (pure Python)

**Files:** Create `backend/app/observation/funnel/reading_order.py`. Test: `backend/tests/observation/test_reading_order.py`

**Interfaces:** Produces `ReadingOrderFormatter(max_elements:int=120)` with `apply(indexed) -> tuple[list[Element], int]`. Sorts elements into reading order (top-to-bottom, then left-to-right, with a small row tolerance), prefers in-viewport elements when over budget (drops off-screen first), caps at `max_elements`, returns the `Element` contract list (carrying the SoM `index`) + the dropped count. **Re-sorting does not change indices** (indices were assigned by `SoMIndexer`; reading order only affects serialization order).

- [ ] **Step 1: Write the failing test `backend/tests/observation/test_reading_order.py`**

```python
from app.observation.funnel.som import IndexedElement
from app.observation.funnel.reading_order import ReadingOrderFormatter


def _ie(index, x, y, in_vp=True, name="b"):
    return IndexedElement(tag="button", role="button", name=name, value=None,
                          x=x, y=y, width=10, height=10, visible=True, in_viewport=in_vp,
                          index=index, center_x=x + 5, center_y=y + 5)


def test_reading_order_sorts_top_then_left_keeps_indices():
    items = [_ie(1, 100, 200), _ie(2, 10, 10), _ie(3, 90, 10)]
    elements, dropped = ReadingOrderFormatter().apply(items)
    # row y=10 first (left-to-right: index 2 then 3), then y=200 (index 1)
    assert [e.index for e in elements] == [2, 3, 1]
    assert dropped == 0


def test_reading_order_budget_drops_offscreen_first_and_counts():
    items = [_ie(1, 0, 0, in_vp=True), _ie(2, 0, 50, in_vp=False), _ie(3, 0, 100, in_vp=True)]
    elements, dropped = ReadingOrderFormatter(max_elements=2).apply(items)
    kept = {e.index for e in elements}
    assert kept == {1, 3} and dropped == 1   # the off-screen one (2) is dropped
```

- [ ] **Step 2: Run to verify it fails** — `cd backend && uv run pytest tests/observation/test_reading_order.py -v` → FAIL.

- [ ] **Step 3: Create `backend/app/observation/funnel/reading_order.py`**

```python
from __future__ import annotations

from browser_agent_contracts import Element

from app.observation.funnel.som import IndexedElement

_ROW_TOLERANCE = 12.0  # px: elements within this vertical band count as the same row


class ReadingOrderFormatter:
    """Serialize indexed elements in visual reading order, within a budget."""

    def __init__(self, max_elements: int = 120) -> None:
        self._max = max_elements

    def apply(self, indexed: list[IndexedElement]) -> tuple[list[Element], int]:
        # Budget: prefer in-viewport elements; drop off-screen first.
        dropped = 0
        kept = indexed
        if len(indexed) > self._max:
            in_vp = [e for e in indexed if e.in_viewport]
            off = [e for e in indexed if not e.in_viewport]
            kept = (in_vp + off)[: self._max]
            dropped = len(indexed) - len(kept)

        # Reading order: bucket by row (y within tolerance), then sort rows top→down, items left→right.
        ordered = sorted(kept, key=lambda e: (round(e.y / _ROW_TOLERANCE), e.x))
        elements = [
            Element(index=e.index, role=e.role, name=e.name, value=e.value) for e in ordered
        ]
        return elements, dropped
```

- [ ] **Step 4: Run to verify it passes** — `cd backend && uv run pytest tests/observation/test_reading_order.py -v` → 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/observation/funnel/reading_order.py backend/tests/observation/test_reading_order.py
git commit -m "feat(observation): ReadingOrderFormatter (order + budget + droppedCount)"
```

---

### Task 4: Funnel pipeline → Observation (pure Python)

**Files:** Create `backend/app/observation/funnel/pipeline.py`. Test: `backend/tests/observation/test_pipeline.py`

**Interfaces:** Produces `run_funnel(raw: list[RawElement], meta: PageMeta, *, screenshot_ref: str | None) -> tuple[Observation, dict[int, tuple[float, float]]]` — composes `VisibilityFilter → SoMIndexer → ReadingOrderFormatter`, assembles the `Observation` (from `meta`, the `Element` list, `screenshot_ref`, `droppedCount`), and returns the hidden `index → (center_x, center_y)` map.

- [ ] **Step 1: Write the failing test `backend/tests/observation/test_pipeline.py`**

```python
from app.observation.raw import RawElement, PageMeta
from app.observation.funnel.pipeline import run_funnel


def _el(name, x, y, visible=True):
    return RawElement(tag="button", role="button", name=name, value=None,
                      x=x, y=y, width=10, height=10, visible=visible, in_viewport=True)


def test_pipeline_builds_observation_and_index_map():
    meta = PageMeta(url="https://x", title="X", viewport_width=1280, viewport_height=800)
    raw = [_el("Login", 10, 10), _el("hidden", 0, 0, visible=False), _el("Email", 10, 40)]
    obs, index_map = run_funnel(raw, meta, screenshot_ref="s1")
    assert obs.url == "https://x" and obs.title == "X" and obs.screenshot_ref == "s1"
    assert [e.name for e in obs.elements] == ["Login", "Email"]          # hidden dropped
    assert [e.index for e in obs.elements] == [1, 2]
    assert index_map[1] == (15.0, 15.0) and index_map[2] == (15.0, 45.0)  # click centers
    assert obs.dropped_count == 0
    # contract guarantee: no coordinates leak into the Observation elements
    assert not any(hasattr(e, "center_x") for e in obs.elements)
```

- [ ] **Step 2: Run to verify it fails** — `cd backend && uv run pytest tests/observation/test_pipeline.py -v` → FAIL.

- [ ] **Step 3: Create `backend/app/observation/funnel/pipeline.py`**

```python
from __future__ import annotations

from browser_agent_contracts import Observation, Viewport

from app.observation.funnel.reading_order import ReadingOrderFormatter
from app.observation.funnel.som import SoMIndexer
from app.observation.funnel.visibility import VisibilityFilter
from app.observation.raw import PageMeta, RawElement


def run_funnel(
    raw: list[RawElement], meta: PageMeta, *, screenshot_ref: str | None = None
) -> tuple[Observation, dict[int, tuple[float, float]]]:
    visible = VisibilityFilter().apply(raw)
    indexed = SoMIndexer().apply(visible)
    index_map = {e.index: (e.center_x, e.center_y) for e in indexed}
    elements, dropped = ReadingOrderFormatter().apply(indexed)
    observation = Observation(
        url=meta.url,
        title=meta.title,
        viewport=Viewport(
            width=meta.viewport_width, height=meta.viewport_height,
            scrollX=meta.scroll_x, scrollY=meta.scroll_y,
        ),
        elements=elements,
        screenshotRef=screenshot_ref,
        droppedCount=dropped,
    )
    return observation, index_map
```

- [ ] **Step 4: Run to verify it passes** — `cd backend && uv run pytest tests/observation/test_pipeline.py -v` → 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/observation/funnel/pipeline.py backend/tests/observation/test_pipeline.py
git commit -m "feat(observation): funnel pipeline → Observation + hidden index→geometry map"
```

---

### Task 5: Extract — JS DOM-walker + `extract(page)` (integration)

**Files:** Create `backend/app/observation/extract.py`. Test: `backend/tests/observation/test_extract_live.py`

**Interfaces:** Produces `EXTRACT_JS` (a JS expression string) and `async extract(page) -> tuple[list[RawElement], PageMeta]` that runs the script via `page.evaluate` and parses the result. The JS returns interactive candidates with **viewport-relative** geometry (`getBoundingClientRect`) + visibility flags + page meta.

- [ ] **Step 1: Write the failing test `backend/tests/observation/test_extract_live.py`** (create `backend/tests/browser/__init__.py` is not needed here; this lives under tests/observation)

```python
import pytest
from playwright.async_api import async_playwright
from app.observation.extract import extract
from app.observation.raw import RawElement, PageMeta

pytestmark = pytest.mark.browser  # slow / needs Chromium

_HTML = """
<html><head><title>Fix</title></head><body>
  <h1>Heading</h1>
  <button id="b">Login</button>
  <input id="e" placeholder="Email">
  <a href="#">A link</a>
  <div style="display:none"><button>hidden</button></div>
</body></html>
"""


async def test_extract_returns_interactive_elements():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await (await browser.new_context()).new_page()
        await page.set_content(_HTML)
        raw, meta = await extract(page)
        await browser.close()
    assert isinstance(meta, PageMeta) and meta.title == "Fix"
    names = {e.name for e in raw}
    assert "Login" in names and "Email" in names and "A link" in names
    # the heading is not interactive; the display:none button is not visible
    assert "Heading" not in names
    assert all(isinstance(e, RawElement) for e in raw)
    assert any(e.width > 0 for e in raw)
```

- [ ] **Step 2: Register the `browser` marker** — append to `backend/pyproject.toml` `[tool.pytest.ini_options]`:

```toml
markers = ["browser: integration tests that launch headless Chromium (slow)"]
```

- [ ] **Step 3: Run to verify it fails** — `cd backend && uv run pytest tests/observation/test_extract_live.py -v` → FAIL (`No module named 'app.observation.extract'`).

- [ ] **Step 4: Create `backend/app/observation/extract.py`**

```python
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
```

- [ ] **Step 5: Run to verify it passes** — `cd backend && uv run pytest tests/observation/test_extract_live.py -v` → 1 passed (launches Chromium; ~1–2s).

- [ ] **Step 6: Commit**

```bash
git add backend/app/observation/extract.py backend/tests/observation/test_extract_live.py backend/pyproject.toml
git commit -m "feat(observation): JS DOM-walker Extract (interactive candidates + geometry)"
```

---

### Task 6: LocalCDPSession.observe (integration)

**Files:** Create `backend/app/browser/local_cdp.py`. Test: `backend/tests/browser/__init__.py`, `backend/tests/browser/test_local_cdp_observe.py`

**Interfaces:** Produces `LocalCDPSession` (satisfies `BrowserSession`) with `async start()`/`stop()`, a `page` property, an `index_map: dict[int, tuple[float,float]]`, a `latest_screenshot: bytes | None`, and `async observe(*, include_som=True) -> Observation` — runs `extract` → `run_funnel` → captures a screenshot (stored; ref = `f"shot-{counter}"`), stores the index_map, returns the `Observation`. `navigate(url)` does `page.goto`. (`act`/`tabs` land in Task 7 but the class is created here with stubs raising `NotImplementedError`, replaced in Task 7.)

- [ ] **Step 1: Write the failing test `backend/tests/browser/test_local_cdp_observe.py`** (create `backend/tests/browser/__init__.py` empty first)

```python
import pytest
from app.browser.local_cdp import LocalCDPSession
from app.browser.base import BrowserSession
from browser_agent_contracts import Observation

pytestmark = pytest.mark.browser

_HTML = "<html><head><title>T</title></head><body><button>Go</button><input placeholder='Q'></body></html>"


async def test_observe_returns_numbered_observation():
    sess = LocalCDPSession()
    await sess.start()
    try:
        assert isinstance(sess, BrowserSession)
        await sess.page.set_content(_HTML)
        obs = await sess.observe()
        assert isinstance(obs, Observation) and obs.title == "T"
        names = {e.name for e in obs.elements}
        assert "Go" in names and "Q" in names
        assert sess.latest_screenshot is not None and obs.screenshot_ref is not None
        assert set(sess.index_map.keys()) == {e.index for e in obs.elements}
    finally:
        await sess.stop()
```

- [ ] **Step 2: Run to verify it fails** — `cd backend && uv run pytest tests/browser/test_local_cdp_observe.py -v` → FAIL.

- [ ] **Step 3: Create `backend/app/browser/local_cdp.py`**

```python
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
```

- [ ] **Step 4: Run to verify it passes** — `cd backend && uv run pytest tests/browser/test_local_cdp_observe.py -v` → 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/browser/local_cdp.py backend/tests/browser
git commit -m "feat(browser): LocalCDPSession.observe (Playwright + funnel → Observation)"
```

---

### Task 7: LocalCDPSession.act / navigate / tabs — trusted input dispatch (integration)

**Files:** Modify `backend/app/browser/local_cdp.py`. Test: `backend/tests/browser/test_local_cdp_act.py`

**Interfaces:** Replaces the `act`/`tabs` stubs. `act(call)` dispatches by `call.name`: `click` → resolve `index_map[args["index"]]` → `page.mouse.click(cx, cy)`; `type` → click the index then `page.keyboard.type(args["text"])` (or `insert_text`); `scroll` → `page.mouse.wheel(0, ±N)`; `navigate` → `navigate(args["url"])`; `wait_for` → bounded sleep; `extract` → return page text. Each wrapped in a per-action timeout (`asyncio.wait_for`) → `ActionResult(success=False, error_code="ACTION_TIMEOUT")` on timeout. After a mutating action, **settle** (`page.wait_for_load_state` with a short bounded timeout, swallow timeout). Unknown index → `ActionResult(success=False, reason="stale index")`. `tabs()` maps `context.pages` → `TabInfo`.

- [ ] **Step 1: Write the failing test `backend/tests/browser/test_local_cdp_act.py`**

```python
import pytest
from app.browser.local_cdp import LocalCDPSession
from browser_agent_contracts import ActionCall

pytestmark = pytest.mark.browser

_HTML = """
<html><body>
  <button id="b" onclick="document.getElementById('out').innerText='clicked'">Click me</button>
  <input id="i">
  <div id="out">idle</div>
</body></html>
"""


async def test_click_by_index_triggers_handler():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content(_HTML)
        obs = await sess.observe()
        btn = next(e for e in obs.elements if e.name == "Click me")
        res = await sess.act(ActionCall(name="click", args={"index": btn.index}))
        assert res.success
        assert await sess.page.inner_text("#out") == "clicked"
    finally:
        await sess.stop()


async def test_type_by_index_fills_input():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content(_HTML)
        obs = await sess.observe()
        inp = next(e for e in obs.elements if e.role == "input" or e.tag == "input")
        await sess.act(ActionCall(name="type", args={"index": inp.index, "text": "hello"}))
        assert await sess.page.input_value("#i") == "hello"
    finally:
        await sess.stop()


async def test_stale_index_fails_gracefully():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content(_HTML)
        await sess.observe()
        res = await sess.act(ActionCall(name="click", args={"index": 999}))
        assert not res.success and "stale" in res.reason.lower()
    finally:
        await sess.stop()
```

*(Note: `Element` has no `tag` field — it is the contract `Element{index,role,name,value}`. The `input` element's `role` is `"input"` because the Extract JS sets `role = el.getAttribute('role') || tagName`. So select by `e.role == "input"`.)*

- [ ] **Step 2: Run to verify it fails** — `cd backend && uv run pytest tests/browser/test_local_cdp_act.py -v` → FAIL (`NotImplementedError`).

- [ ] **Step 3: Replace `act`/`tabs` in `backend/app/browser/local_cdp.py`** — add the imports `import asyncio` and `from playwright.async_api import TimeoutError as PWTimeout` at the top, and replace the two stub methods with:

```python
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
```

- [ ] **Step 4: Run to verify it passes** — `cd backend && uv run pytest tests/browser/test_local_cdp_act.py -v` → 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/browser/local_cdp.py backend/tests/browser/test_local_cdp_act.py
git commit -m "feat(browser): LocalCDPSession trusted-input act/scroll/type + settle + tabs"
```

---

### Task 8: Container wiring + real-browser e2e (integration)

**Files:** Modify `backend/app/config/settings.py`, `backend/app/config/container.py`. Create `backend/app/agent/run_browser.py`. Test: `backend/tests/agent/test_real_browser_e2e.py`

**Interfaces:** Adds `browser_backend: str = "fake"` to settings. `build_default_app(*, session=None, llm=None, sink=None)` — when `session is None`, builds a `LocalCDPSession` if `settings.browser_backend == "local_cdp"`, else raises (a session must be provided or configured). Adds `run_browser.run_on_html(html, task, llm)` test helper. The e2e drives the **real funnel + real browser** with a **scripted fake LLM** (no API spend): observe a fixture → click the indexed button → `complete()`.

- [ ] **Step 1: Add `browser_backend` to `backend/app/config/settings.py`** (inside `Settings`, after `llm_max_retries`):

```python
    browser_backend: str = "fake"  # "fake" | "local_cdp"
```

- [ ] **Step 2: Update `build_default_app` in `backend/app/config/container.py`** — change the signature to `def build_default_app(*, session=None, llm=None, sink: EventSink | None = None):` and, right after computing `settings`, insert:

```python
    if session is None:
        if settings.browser_backend == "local_cdp":
            from app.browser.local_cdp import LocalCDPSession
            session = LocalCDPSession()  # caller must `await session.start()` before running
        else:
            raise ValueError("No session provided and browser_backend is not 'local_cdp'.")
```

*(Keep the rest of `build_default_app` unchanged. Existing callers pass `session=` explicitly, so they're unaffected.)*

- [ ] **Step 3: Write the failing test `backend/tests/agent/test_real_browser_e2e.py`**

```python
import pytest
from browser_agent_contracts import Observation
from app.browser.local_cdp import LocalCDPSession
from app.config.container import build_default_app
from app.agent.demo import run
from tests.fakes.fake_llm import FakeLLMClient, ai

pytestmark = pytest.mark.browser

_HTML = """
<html><body>
  <button onclick="document.title='DONE'">Finish</button>
</body></html>
"""


async def test_agent_clicks_real_button_then_completes():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content(_HTML)
        first = await sess.observe()                       # peek to learn the button index
        idx = next(e.index for e in first.elements if e.name == "Finish")
        llm = FakeLLMClient(turns=[
            ai("I'll click Finish", [{"name": "Click", "args": {"index": idx}, "id": "a"}]),
            ai("Title changed; done", [{"name": "Complete", "args": {"success": True, "reason": "done"}, "id": "b"}]),
        ])
        graph, *_ = build_default_app(session=sess, llm=llm)
        final = await run(graph, task="click finish", thread_id="rb1")
        assert final.status == "done" and final.success is True
        assert await sess.page.title() == "DONE"           # the agent really clicked it
    finally:
        await sess.stop()
```

- [ ] **Step 4: Run to verify it fails, then passes** — `cd backend && uv run pytest tests/agent/test_real_browser_e2e.py -v` → after Steps 1–2 it should PASS (the real funnel + browser + B1 loop drive the click). If it fails, read the error: a stale index means `observe()` ran twice (the `run` re-observes) — the fixture is static so indices are stable; confirm the button index from `first` matches.

- [ ] **Step 5: Run the FULL suite** — `cd backend && uv run pytest -q` → all green (fast unit tests + the `browser`-marked integration tests + the B1/B2 suite). Confirm pristine.

- [ ] **Step 6: Commit**

```bash
git add backend/app/config/settings.py backend/app/config/container.py backend/app/agent/run_browser.py backend/tests/agent/test_real_browser_e2e.py
git commit -m "feat(browser): config-gated LocalCDPSession + real-browser e2e (agent clicks a real page)"
```

*(Note: create `backend/app/agent/run_browser.py` as a thin `async def run_on_html(html, task, llm, *, thread_id="browser")` helper that starts a `LocalCDPSession`, `set_content(html)`, builds the app, runs, and stops — mirroring the e2e flow — so there's a reusable entry point. Keep it minimal.)*

---

## Self-Review

**Spec coverage (design spec §4 funnel, §5 actions, §7.6 real eyes):**
- `LocalCDPSession` over Playwright/Chromium satisfying `BrowserSession` (zero graph changes) → Tasks 6–8. ✓
- Funnel stages `Extract → Visibility → SoM → ReadingOrder` → Tasks 1–5; Occlusion/WrapperCollapse explicitly deferred (B3.1). ✓
- `Observation` carries numbered elements + screenshot ref + droppedCount, **no coordinates/raw DOM** (coords only in the hidden index_map) → Tasks 4, 6 (test asserts no coord leak). ✓
- Trusted input via Playwright mouse/keyboard (CDP-backed) → Task 7. ✓
- Per-action timeout walls (`ACTION_TIMEOUT`); settle before re-observe → Task 7. ✓
- No silent truncation — `droppedCount` set, off-screen dropped first → Task 3. ✓
- Indices rebuilt every observe → Task 6 (each `observe` rebuilds index_map). ✓
- Swap fake→real with zero graph changes; config-gated → Task 8. ✓
- **Out of scope:** `OcclusionCuller`/`WrapperCollapser` (B3.1), adaptive per-host settle, the extension (M4), persistent memory/compaction (B4).

**Placeholder scan:** No "TBD/handle errors". The integration tests use `page.set_content` fixtures (no fixture server). Task 6 ships `act`/`tabs` as `NotImplementedError` stubs **only** within the same plan, completed in Task 7 — not a shipped placeholder.

**Type consistency:** `RawElement`/`PageMeta`/`IndexedElement`, `VisibilityFilter.apply`/`SoMIndexer.apply`/`ReadingOrderFormatter.apply`, `run_funnel(raw, meta, *, screenshot_ref) -> (Observation, index_map)`, `extract(page) -> (list[RawElement], PageMeta)`, `LocalCDPSession.observe/act/navigate/tabs` + `index_map`/`latest_screenshot`, and the `ActionCall.name` dispatch keys (`click/type/scroll/navigate/wait_for/extract`) are consistent across Tasks 1–8 and match the B1 `BrowserSession`/`Observation`/`ActionCall` contracts. ✓

**Note for the implementer:** the `browser`-marked integration tests launch real Chromium (~1–2s each). They run in the default suite; to skip them in a fast loop use `-m "not browser"`. Chromium is already installed (`playwright install chromium` from Phase A `just setup`).
```
