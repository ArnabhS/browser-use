import pytest
from playwright.async_api import async_playwright
from app.observation.extract import extract

pytestmark = pytest.mark.browser

_HTML = """
<html><body>
  <button id="under" style="position:absolute;top:50px;left:50px;width:100px;height:40px">Under</button>
  <div style="position:absolute;top:40px;left:40px;width:200px;height:200px;background:red;z-index:10">cover</div>
  <button id="clear" style="position:absolute;top:300px;left:50px;width:100px;height:40px">Clear button</button>
</body></html>
"""


async def test_occluded_button_flagged_visible_button_not():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        page = await (await b.new_context()).new_page()
        await page.set_content(_HTML)
        raw, _ = await extract(page)
        await b.close()
    by_name = {e.name: e for e in raw}
    assert by_name["Under"].occluded is True       # covered by the red div
    assert by_name["Clear button"].occluded is False
