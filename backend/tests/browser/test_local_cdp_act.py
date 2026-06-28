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
        inp = next(e for e in obs.elements if e.role == "input")
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


async def test_missing_index_fails_closed_not_raises():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content(_HTML)
        await sess.observe()
        res = await sess.act(ActionCall(name="click", args={}))  # no index key
        assert not res.success and res.error_code == "ACTION_ERROR"
    finally:
        await sess.stop()
