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
