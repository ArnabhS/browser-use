"""Stealth strips the obvious automation tells so bot-walls serve the real page. The load-bearing
lever is running headful (verified live: headful loads real Skyscanner, headless gets the PerimeterX
captcha) — these tests pin the cheap JS/arg defense-in-depth layered on top: navigator.webdriver
must not read as an automated browser when stealth is on."""
import pytest

from app.browser.local_cdp import LocalCDPSession

pytestmark = pytest.mark.browser


async def test_stealth_hides_webdriver_flag():
    sess = LocalCDPSession(stealth=True)
    await sess.start()
    try:
        wd = await sess.page.evaluate("() => navigator.webdriver")
        assert not wd, f"navigator.webdriver leaked with stealth on: {wd!r}"
    finally:
        await sess.stop()


async def test_webdriver_flag_present_without_stealth():
    sess = LocalCDPSession(stealth=False)
    await sess.start()
    try:
        wd = await sess.page.evaluate("() => navigator.webdriver")
        assert wd is True, f"expected the automation flag without stealth, got {wd!r}"
    finally:
        await sess.stop()


async def test_stealth_init_script_applies_inside_iframes():
    """The init script runs in every frame — so an iframe'd form (HubSpot etc.) is also clean."""
    sess = LocalCDPSession(stealth=True)
    await sess.start()
    try:
        await sess.page.set_content("<iframe srcdoc='<button>x</button>'></iframe>")
        child = next(f for f in sess.page.frames if f != sess.page.main_frame)
        wd = await child.evaluate("() => navigator.webdriver")
        assert not wd, f"navigator.webdriver leaked inside iframe: {wd!r}"
    finally:
        await sess.stop()
