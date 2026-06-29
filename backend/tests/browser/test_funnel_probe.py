"""Diagnostics for the 'I can SEE Add-to-cart but it's never in the element list' bug.
The DOM probe must reveal the root cause for both common failure modes, and observe() must
indeed omit the element — proving the instrumentation catches what the agent hits live."""
import pytest

from app.browser.local_cdp import LocalCDPSession
from app.observation.extract import probe_dom

pytestmark = pytest.mark.browser


async def test_probe_flags_a_noninteractive_div_button_as_unextractable():
    sess = LocalCDPSession(funnel_debug=True, funnel_focus="add to cart")
    await sess.start()
    try:
        # A <div> styled as a button with only a JS listener — no <button>/role/onclick attr/
        # tabindex. Exactly the kind of control the extractor's isInteractive() can't see.
        await sess.page.set_content(
            "<div style='padding:40px'>"
            "<div id='atc' style='cursor:pointer;font-size:30px'>ADD TO CART</div>"
            "</div>"
            "<script>document.getElementById('atc').addEventListener('click',()=>{})</script>"
        )
        obs = await sess.observe()
        assert not any("add to cart" in (e.name or "").lower() for e in obs.elements)

        probe = await probe_dom(sess.page, "add to cart")
        atc = next(p for p in probe if "add to cart" in p["text"].lower())
        assert atc["would_extract"] is False     # ROOT CAUSE made visible: not interactive
        assert atc["cursor"] == "pointer"         # ...yet clearly meant to be clicked
    finally:
        await sess.stop()


async def test_probe_flags_occlusion_of_a_real_button():
    sess = LocalCDPSession()
    await sess.start()
    try:
        # A real <button> covered by a transparent full-screen overlay → elementFromPoint at its
        # centre returns the overlay, so the occluded flag culls a perfectly clickable button.
        await sess.page.set_content(
            "<button style='position:fixed;bottom:0;left:0;width:200px;height:50px'>ADD TO CART</button>"
            "<div style='position:fixed;inset:0;z-index:9999;background:transparent'></div>"
        )
        obs = await sess.observe()
        assert not any("add to cart" in (e.name or "").lower() for e in obs.elements)

        probe = await probe_dom(sess.page, "add to cart")
        atc = next(p for p in probe if "add to cart" in p["text"].lower())
        assert atc["would_extract"] is True       # it IS interactive
        assert atc["hit_is_self_or_child"] is False  # ...but the overlay wins the hit-test
    finally:
        await sess.stop()
