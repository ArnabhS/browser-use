"""Interactivity via real event listeners. Our old detection only caught React handlers (fiber
props); a plain <div>/<span> wired with addEventListener('click', …) by Vue/Svelte/vanilla was
invisible. A CDP getEventListeners pre-pass now flags them."""
import pytest

from app.browser.local_cdp import LocalCDPSession

pytestmark = pytest.mark.browser


async def test_plain_div_with_click_listener_is_interactable():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content(
            '<div id="x" style="position:absolute;top:40px;left:40px;width:100px;height:30px">ClickMe</div>'
        )
        # a real listener, no role / onclick attr / tabindex / React — undetectable before
        await sess.page.evaluate("() => document.getElementById('x').addEventListener('click', () => {})")
        obs = await sess.observe()
        assert any("clickme" in (e.name or "").lower() for e in obs.elements)
    finally:
        await sess.stop()


async def test_plain_div_without_listener_stays_non_interactive():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content(
            '<div style="position:absolute;top:40px;left:40px;width:100px;height:30px">JustText</div>'
        )
        obs = await sess.observe()
        assert not any("justtext" in (e.name or "").lower() for e in obs.elements)
    finally:
        await sess.stop()
