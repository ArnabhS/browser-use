"""Track B parity: the raw-CDP CDPSession must drive the core loop — observe the funnel, click, and
type — the same way LocalCDPSession does, against real Chrome."""
import urllib.parse

import pytest
from browser_agent_contracts import ActionCall

from app.browser.cdp_session import CDPSession

pytestmark = pytest.mark.browser

_FIXTURE = "data:text/html," + urllib.parse.quote(
    "<html><body>"
    "<button id='a'>Alpha</button>"
    "<button id='b' onclick=\"document.getElementById('hidden').style.display='block'\">Reveal</button>"
    "<div id='hidden' style='display:none'><button>Surprise</button></div>"
    "<input id='in' placeholder='Email'>"
    "</body></html>"
)


async def _started(**kw):
    # load_extensions=False keeps the tests hermetic (no Chrome Web Store download).
    s = CDPSession(headless=True, stealth=True, load_extensions=False, **kw)
    await s.start()
    return s


async def test_cdp_observe_finds_buttons_and_input():
    s = await _started()
    try:
        await s.navigate(_FIXTURE)
        obs = await s.observe()
        names = {e.name for e in obs.elements}
        assert "Alpha" in names and "Reveal" in names
        assert "Email" in names            # input named by its placeholder
    finally:
        await s.stop()


async def test_cdp_click_reveals_new_element():
    s = await _started()
    try:
        await s.navigate(_FIXTURE)
        obs = await s.observe()
        reveal = next(e for e in obs.elements if e.name == "Reveal")
        res = await s.act(ActionCall(name="click", args={"index": reveal.index}))
        assert res.success
        obs2 = await s.observe()
        assert any(e.name == "Surprise" for e in obs2.elements)
    finally:
        await s.stop()


async def test_cdp_type_sets_input_value():
    s = await _started()
    try:
        await s.navigate(_FIXTURE)
        obs = await s.observe()
        inp = next(e for e in obs.elements if e.name == "Email")
        res = await s.act(ActionCall(name="type", args={"index": inp.index, "text": "hi@x.com"}))
        assert res.success
        assert await s._eval("document.getElementById('in').value") == "hi@x.com"
    finally:
        await s.stop()


_IFRAME = "data:text/html," + urllib.parse.quote(
    '<iframe width=300 height=200 style="position:absolute;left:50px;top:80px;border:0" '
    "srcdoc=\"<button style='position:absolute;left:10px;top:20px' "
    "onclick='this.textContent=&quot;Done&quot;'>InnerBtn</button>\"></iframe>"
)


async def test_cdp_extracts_and_clicks_inside_child_iframe():
    s = await _started()
    try:
        await s.navigate(_IFRAME)
        obs = await s.observe()
        btn = next(e for e in obs.elements if e.name == "InnerBtn")
        cx, cy = s.index_map[btn.index]
        assert 50 < cx < 360 and 80 < cy < 290       # offset into the PARENT viewport, not frame-local
        await s.act(ActionCall(name="click", args={"index": btn.index}))
        obs2 = await s.observe()
        assert any(e.name == "Done" for e in obs2.elements)  # the trusted click landed inside the iframe
    finally:
        await s.stop()


async def test_cdp_stealth_hides_webdriver():
    s = await _started()
    try:
        await s.navigate("about:blank")
        assert not await s._eval("navigator.webdriver")
    finally:
        await s.stop()


async def test_cdp_emulation_overrides_locale_and_timezone():
    s = await _started(locale="en-IN", timezone="Asia/Kolkata")
    try:
        await s.navigate("about:blank")
        # Chrome/ICU returns the legacy alias "Asia/Calcutta" for "Asia/Kolkata" — either means the
        # override took (it is not the host default).
        assert await s._eval("Intl.DateTimeFormat().resolvedOptions().timeZone") in {"Asia/Kolkata", "Asia/Calcutta"}
        assert await s._eval("navigator.language") == "en-IN"
    finally:
        await s.stop()


_HOLD = "data:text/html," + urllib.parse.quote(
    "<button id='h' onmousedown='window.__d=performance.now()' "
    "onmouseup='window.__h=performance.now()-window.__d'>Hold</button>"
)


async def test_cdp_long_press_holds_for_the_duration():
    s = await _started()
    try:
        await s.navigate(_HOLD)
        obs = await s.observe()
        hold = next(e for e in obs.elements if e.name == "Hold")
        res = await s.act(ActionCall(name="long_press", args={"index": hold.index, "duration_ms": 300}))
        assert res.success
        assert await s._eval("window.__h") >= 250  # actually held, not an instant click
    finally:
        await s.stop()


_SELECT = "data:text/html," + urllib.parse.quote(
    "<select id='sel'><option value='a'>Apple</option><option value='b'>Banana</option></select>"
)


async def test_cdp_select_option_by_text():
    s = await _started()
    try:
        await s.navigate(_SELECT)
        obs = await s.observe()
        sel = next(e for e in obs.elements if e.role == "select")
        res = await s.act(ActionCall(name="select_option", args={"index": sel.index, "value": "Banana"}))
        assert res.success
        assert await s._eval("document.getElementById('sel').value") == "b"
    finally:
        await s.stop()


async def test_cdp_observe_draws_som_overlay_into_the_screenshot():
    s = await _started(draw_som_overlay=True)
    try:
        await s.navigate(_FIXTURE)
        await s.observe()               # overlay drawn into latest_screenshot, then removed
        with_som = s.latest_screenshot
        plain = await s._screenshot()    # overlay already gone → a clean capture of the same page
        assert with_som and plain
        assert with_som != plain         # the numbered boxes changed the vision screenshot
        # overlay must not linger — it would block hit-testing on the next action
        assert await s._eval("!!document.getElementById('__som_overlay__')") is False
    finally:
        await s.stop()


async def test_cdp_screencast_pushes_frames():
    import asyncio

    frames = []

    async def on_frame(data_b64, meta):
        frames.append((data_b64, meta))

    s = await _started()
    s.on_frame = on_frame
    try:
        await s.start_stream()          # stream first (as production does), then cause repaints
        await s.navigate(_FIXTURE)
        await s.act(ActionCall(name="scroll", args={"direction": "down"}))
        for _ in range(30):
            if frames:
                break
            await asyncio.sleep(0.1)
        assert frames, "expected at least one screencast frame"
        assert frames[0][0]  # non-empty base64 jpeg
    finally:
        await s.stop()


async def test_cdp_search_page_finds_and_misses():
    s = await _started()
    try:
        await s.navigate(_FIXTURE)
        hit = await s.act(ActionCall(name="search_page", args={"pattern": "Reveal"}))
        assert hit.success and "Reveal" in hit.reason
        miss = await s.act(ActionCall(name="search_page", args={"pattern": "zzz-not-here"}))
        assert miss.success and "no matches" in miss.reason
    finally:
        await s.stop()


async def test_cdp_find_elements_by_selector():
    s = await _started()
    try:
        await s.navigate(_FIXTURE)
        res = await s.act(ActionCall(name="find_elements",
                                     args={"index": 0, "selector": "button", "attributes": ["id"]}))
        assert res.success
        assert "element(s) match" in res.reason and "id='a'" in res.reason
    finally:
        await s.stop()


async def test_cdp_new_switch_and_close_tabs():
    s = await _started()
    try:
        await s.navigate(_FIXTURE)
        assert (await s.act(ActionCall(name="new_tab",
                args={"url": "data:text/html,<body>second</body>"}))).success
        tabs = await s.tabs()
        assert len(tabs) >= 2
        assert "second" in (await s._eval("document.body.innerText"))     # active tab is the new one
        assert [t for t in tabs if t.active][0].id == 1
        assert (await s.act(ActionCall(name="switch_tab", args={"target_id": "0"}))).success
        assert "Alpha" in (await s._eval("document.body.innerText"))       # back on the fixture
        assert (await s.act(ActionCall(name="close_tab", args={"target_id": "1"}))).success
        assert len(await s.tabs()) == 1
    finally:
        await s.stop()
