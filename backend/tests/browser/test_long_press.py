"""LongPress presses and HOLDS the element for a duration, then releases — for touch-style
press-and-hold interactions. The fixture only marks itself 'held' when mouseup lands ≥500ms after
mousedown, so a real hold is required to pass (a normal Click must NOT trigger it)."""
import pytest

from browser_agent_contracts import ActionCall

from app.browser.local_cdp import LocalCDPSession

pytestmark = pytest.mark.browser

_FIXTURE = (
    "<button id='b' style='width:140px;height:44px'>hold me</button>"
    "<script>"
    "let t=0;const b=document.getElementById('b');"
    "b.addEventListener('mousedown',()=>{t=Date.now();});"
    "b.addEventListener('mouseup',()=>{ if(Date.now()-t>=500){ b.setAttribute('data-held','1'); } });"
    "</script>"
)


async def _index_of_hold(sess) -> int:
    obs = await sess.observe()
    return next(e.index for e in obs.elements if "hold" in (e.name or "").lower())


async def test_long_press_holds_before_releasing():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content(_FIXTURE)
        idx = await _index_of_hold(sess)
        res = await sess.act(ActionCall(name="long_press", args={"index": idx, "duration_ms": 800}))
        assert res.success, res.reason
        assert await sess.page.get_attribute("#b", "data-held") == "1"
    finally:
        await sess.stop()


async def test_normal_click_does_not_trigger_hold():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content(_FIXTURE)
        idx = await _index_of_hold(sess)
        res = await sess.act(ActionCall(name="click", args={"index": idx}))
        assert res.success
        assert await sess.page.get_attribute("#b", "data-held") is None  # too fast to count as a hold
    finally:
        await sess.stop()


async def test_long_press_stale_index_fails_cleanly():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content(_FIXTURE)
        res = await sess.act(ActionCall(name="long_press", args={"index": 999, "duration_ms": 800}))
        assert res.success is False
        assert "stale" in res.reason.lower()
    finally:
        await sess.stop()
