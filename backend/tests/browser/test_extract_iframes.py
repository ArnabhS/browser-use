"""Forms embedded in iframes (HubSpot/Typeform/Stripe embeds — e.g. quashbugs.com/contact-form)
live in a CHILD frame, which `page.evaluate` never sees: the funnel extracted 0 of the form's
fields, so the agent was blind to the whole form. The funnel must extract every (real-sized) child
frame too, offsetting coordinates by the iframe's position so trusted clicks/typing at viewport
coords land inside the frame."""
import asyncio

import pytest

from browser_agent_contracts import ActionCall

from app.browser.local_cdp import LocalCDPSession

pytestmark = pytest.mark.browser

_PARENT = """
<h1>Parent page</h1>
<button style="width:120px;height:36px">Parent button</button>
<iframe style="position:absolute; left:100px; top:150px; width:420px; height:320px; border:0"
        srcdoc='<input placeholder="Email address" style="width:250px;height:36px">
                <button style="width:120px;height:36px">Send it</button>'></iframe>
"""


async def _obs_after_frames(sess):
    await sess.page.set_content(_PARENT)
    await asyncio.sleep(0.3)  # let the srcdoc frame attach
    return await sess.observe()


async def test_iframe_fields_appear_with_offset_coordinates():
    sess = LocalCDPSession()
    await sess.start()
    try:
        obs = await _obs_after_frames(sess)
        names = [(e.name or "") for e in obs.elements]
        assert any("Email address" in n for n in names), names
        assert any("Send it" in n for n in names), names
        assert any("Parent button" in n for n in names), names  # main frame still extracted

        # the hidden coordinate map must be OFFSET into the parent viewport (iframe at 100,150)
        idx = next(e.index for e in obs.elements if "Email address" in (e.name or ""))
        cx, cy = sess.index_map[idx]
        assert cx > 100 and cy > 150, (cx, cy)
    finally:
        await sess.stop()


async def test_typing_into_iframe_field_round_trips():
    sess = LocalCDPSession()
    await sess.start()
    try:
        obs = await _obs_after_frames(sess)
        idx = next(e.index for e in obs.elements if "Email address" in (e.name or ""))
        res = await sess.act(ActionCall(name="type", args={"index": idx, "text": "a@b.test"}))
        assert res.success, res.reason
        child = next(f for f in sess.page.frames if f != sess.page.main_frame)
        assert await child.evaluate("document.querySelector('input').value") == "a@b.test"
    finally:
        await sess.stop()


async def test_scaled_iframe_coordinates_account_for_css_transform():
    """Sites shrink embeds with CSS transform: scale(…) (quashbugs.com scales its HubSpot form to
    ~0.85). bounding_box() reports the RENDERED box but in-frame coords are unscaled — without
    applying the scale, clicks land ~40px off and focus the wrong field (seen live: typing 'email'
    focused the phone input). Typing through the funnel coords must land in the right field."""
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content(
            "<iframe style='position:absolute; left:100px; top:100px; width:400px; height:300px;"
            " border:0; transform:scale(0.5); transform-origin:0 0'"
            " srcdoc='<input placeholder=\"Scaled field\" style=\"width:300px;height:40px\">'></iframe>"
        )
        await asyncio.sleep(0.3)
        obs = await sess.observe()
        idx = next(e.index for e in obs.elements if "Scaled field" in (e.name or ""))
        res = await sess.act(ActionCall(name="type", args={"index": idx, "text": "hit"}))
        assert res.success, res.reason
        child = next(f for f in sess.page.frames if f != sess.page.main_frame)
        assert await child.evaluate("document.querySelector('input').value") == "hit"
    finally:
        await sess.stop()


async def test_hidden_iframe_fields_are_not_extracted():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content(
            "<button style='width:120px;height:36px'>Visible</button>"
            "<iframe style='display:none' srcdoc='<button>Ghost button</button>'></iframe>"
        )
        await asyncio.sleep(0.3)
        obs = await sess.observe()
        names = [(e.name or "") for e in obs.elements]
        assert not any("Ghost button" in n for n in names), names
    finally:
        await sess.stop()
