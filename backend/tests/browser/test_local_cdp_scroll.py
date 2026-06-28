"""Scroll must actually move the viewport (mouse.wheel silently no-op'd on many sites)."""
import pytest

from app.browser.local_cdp import LocalCDPSession
from browser_agent_contracts import ActionCall

pytestmark = pytest.mark.browser


async def test_scroll_moves_the_page():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content("<div style='height:6000px'>tall page</div>")
        y0 = await sess.page.evaluate("() => window.scrollY")
        r = await sess.act(ActionCall(name="scroll", args={"direction": "down", "amount": 3}))
        y1 = await sess.page.evaluate("() => window.scrollY")
        assert r.success is True
        assert y1 > y0 + 1000                      # 3 * 600 ≈ 1800px down
        r2 = await sess.act(ActionCall(name="scroll", args={"direction": "up", "amount": 2}))
        y2 = await sess.page.evaluate("() => window.scrollY")
        assert r2.success is True and y2 < y1      # moved back up
    finally:
        await sess.stop()


async def test_scroll_at_edge_reports_no_movement():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content("<div style='height:100px'>short</div>")
        r = await sess.act(ActionCall(name="scroll", args={"direction": "down", "amount": 3}))
        assert r.success is False                  # nothing to scroll → honest failure
    finally:
        await sess.stop()
