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


async def test_scroll_index_scrolls_the_inner_container_not_the_window():
    """A modal/feed lives in an overflow:auto box; scroll(index=N) must move THAT box."""
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content(
            "<div id='box' style='height:200px;width:300px;overflow:auto;border:1px solid'>"
            "<div style='height:4000px'>"
            "<button style='margin-top:40px'>topbtn</button>"
            "</div></div>"
            "<div style='height:3000px'>tall body — the WINDOW is scrollable too</div>"
        )
        obs = await sess.observe()
        btn = next(e for e in obs.elements if "topbtn" in (e.name or "").lower())
        win0 = await sess.page.evaluate("() => window.scrollY")
        top0 = await sess.page.evaluate("() => document.getElementById('box').scrollTop")
        r = await sess.act(
            ActionCall(name="scroll", args={"direction": "down", "amount": 2, "index": btn.index})
        )
        top1 = await sess.page.evaluate("() => document.getElementById('box').scrollTop")
        win1 = await sess.page.evaluate("() => window.scrollY")
        assert r.success is True
        assert top1 > top0 + 100                   # the inner container moved
        assert win1 == win0                        # the window did NOT
    finally:
        await sess.stop()
