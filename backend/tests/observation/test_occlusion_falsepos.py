"""OcclusionCuller false positives: a visible, clickable control whose centre merely lands on
an overlapping same-spot wrapper/sibling must NOT be culled (a trusted click still actuates it).
Only a genuine covering surface (a modal/overlay enclosing it) should mark it occluded."""
import pytest
from playwright.async_api import async_playwright

from app.observation.extract import extract

pytestmark = pytest.mark.browser


async def _occluded_map(html: str) -> dict[str, bool]:
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        page = await (await b.new_context()).new_page()
        await page.set_content(html)
        raw, _ = await extract(page)
        await b.close()
    return {e.name: e.occluded for e in raw}


async def test_same_size_overlay_does_not_occlude():
    # A transparent sibling div sits EXACTLY on top of the button (a click-catcher/wrapper,
    # exactly the Flipkart-header pattern). elementFromPoint at the centre returns the div, but
    # the button is fully visible and a trusted click at its coords still actuates that region.
    occ = await _occluded_map(
        "<button id='b' style='position:absolute;top:100px;left:100px;width:120px;height:40px'>"
        "Add to cart</button>"
        "<div style='position:absolute;top:100px;left:100px;width:120px;height:40px;z-index:5'></div>"
    )
    assert occ["Add to cart"] is False


async def test_large_covering_overlay_still_occludes():
    # A big overlay that encloses the button (a modal/banner) genuinely hides it → still culled.
    occ = await _occluded_map(
        "<button id='b' style='position:absolute;top:100px;left:100px;width:100px;height:40px'>"
        "Behind</button>"
        "<div style='position:absolute;top:60px;left:60px;width:300px;height:300px;"
        "background:#fff;z-index:9'>modal</div>"
    )
    assert occ["Behind"] is True
