"""Clicking a product/link that opens in a NEW tab must make the agent follow it,
so the next observation reflects the new page (Flipkart/Myntra open results in _blank)."""
import pytest

from app.browser.local_cdp import LocalCDPSession
from browser_agent_contracts import ActionCall

pytestmark = pytest.mark.browser


async def test_click_follows_target_blank_new_tab():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content(
            '<a href="https://example.com" target="_blank" '
            'style="font-size:40px;display:block;padding:40px">OPEN PRODUCT</a>'
        )
        first = sess.page
        obs = await sess.observe()
        link = next(e for e in obs.elements if "open" in (e.name or "").lower())

        result = await sess.act(ActionCall(name="click", args={"index": link.index}))

        assert sess.page is not first                       # the session switched tabs
        open_pages = [p for p in sess.page.context.pages if not p.is_closed()]
        assert len(open_pages) >= 2                          # original + the spawned tab
        assert "followed new tab" in result.reason
    finally:
        await sess.stop()


async def test_normal_click_does_not_switch_tabs():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content('<button style="font-size:30px">Just a button</button>')
        first = sess.page
        obs = await sess.observe()
        btn = next(e for e in obs.elements if "button" in (e.name or "").lower())
        result = await sess.act(ActionCall(name="click", args={"index": btn.index}))
        assert sess.page is first                            # no new tab → stays put
        assert "followed new tab" not in result.reason
    finally:
        await sess.stop()
