import pytest
from app.browser.local_cdp import LocalCDPSession
from browser_agent_contracts import ActionCall

pytestmark = pytest.mark.browser

_HTML = """
<html><body>
  <input id="i" value="old">
  <select id="s"><option value="a">A</option><option value="b">B</option></select>
  <div id="out">idle</div>
  <script>document.getElementById('s').addEventListener('change',e=>document.getElementById('out').innerText='sel:'+e.target.value)</script>
</body></html>
"""


async def test_clear_then_type_replaces_value():
    sess = LocalCDPSession(); await sess.start()
    try:
        await sess.page.set_content(_HTML)
        obs = await sess.observe()
        inp = next(e for e in obs.elements if e.role == "input")
        await sess.act(ActionCall(name="clear", args={"index": inp.index}))
        await sess.act(ActionCall(name="type", args={"index": inp.index, "text": "new"}))
        assert await sess.page.input_value("#i") == "new"
    finally:
        await sess.stop()


async def test_press_key_dispatches():
    sess = LocalCDPSession(); await sess.start()
    try:
        await sess.page.set_content(_HTML)
        await sess.observe()
        res = await sess.act(ActionCall(name="press_key", args={"key": "Tab"}))
        assert res.success
    finally:
        await sess.stop()


async def test_select_option_sets_value_and_fires_change():
    sess = LocalCDPSession(); await sess.start()
    try:
        await sess.page.set_content(_HTML)
        obs = await sess.observe()
        sel = next(e for e in obs.elements if e.role == "select")
        res = await sess.act(ActionCall(name="select_option", args={"index": sel.index, "value": "B"}))
        assert res.success
        assert await sess.page.inner_text("#out") == "sel:b"
    finally:
        await sess.stop()


async def test_close_active_tab_recovers_to_survivor():
    sess = LocalCDPSession(); await sess.start()
    try:
        await sess.page.set_content("<title>T0</title>")
        await sess.act(ActionCall(name="new_tab", args={"url": "data:text/html,<title>T1</title>"}))
        # the new tab is now active (index 1); close THAT (the active) tab
        res = await sess.act(ActionCall(name="close_tab", args={"target_id": "1"}))
        assert res.success
        assert len(await sess.tabs()) == 1
        obs = await sess.observe()   # session still usable on the surviving tab
        assert obs is not None
    finally:
        await sess.stop()


async def test_new_and_switch_and_close_tab():
    sess = LocalCDPSession(); await sess.start()
    try:
        await sess.page.set_content("<title>T0</title>")
        await sess.act(ActionCall(name="new_tab", args={"url": "data:text/html,<title>T1</title>"}))
        tabs = await sess.tabs()
        assert len(tabs) == 2
        await sess.act(ActionCall(name="switch_tab", args={"target_id": "0"}))
        res = await sess.act(ActionCall(name="close_tab", args={"target_id": "1"}))
        assert res.success and len((await sess.tabs())) == 1
    finally:
        await sess.stop()
