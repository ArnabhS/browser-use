"""The launched browser should present a configured locale/timezone/geolocation (India in prod)
so pages don't see the datacenter's random default. This shapes navigator.language, the Intl
timezone, and the JS Geolocation API — it does NOT change the outbound IP."""
import pytest

from app.browser.local_cdp import LocalCDPSession
from app.config.settings import Settings


@pytest.mark.browser
async def test_context_presents_configured_locale_and_timezone():
    sess = LocalCDPSession(locale="en-IN", timezone="Asia/Kolkata", geolocation=(19.076, 72.8777))
    await sess.start()
    try:
        tz = await sess.page.evaluate("() => Intl.DateTimeFormat().resolvedOptions().timeZone")
        # We pass "Asia/Kolkata"; Chromium's ICU resolves it to the legacy alias "Asia/Calcutta"
        # (same IANA zone) — either proves the timezone override took effect.
        assert tz in ("Asia/Kolkata", "Asia/Calcutta")
        lang = await sess.page.evaluate("() => navigator.language")
        assert lang == "en-IN"
    finally:
        await sess.stop()


def test_context_kwargs_carry_locale_timezone_geolocation():
    # Geolocation needs a secure context to read at runtime (fails on about:blank), so verify we
    # hand Playwright the right options — its job is to apply them once the page is on https.
    kw = LocalCDPSession(
        locale="en-IN", timezone="Asia/Kolkata", geolocation=(19.076, 72.8777)
    )._context_kwargs()
    assert kw["locale"] == "en-IN"
    assert kw["timezone_id"] == "Asia/Kolkata"
    assert kw["geolocation"] == {"latitude": 19.076, "longitude": 72.8777}
    assert kw["permissions"] == ["geolocation"]


def test_context_kwargs_empty_without_overrides():
    assert LocalCDPSession()._context_kwargs() == {}


def test_settings_default_to_india():
    s = Settings(_env_file=None)
    assert s.browser_locale == "en-IN"
    assert s.browser_timezone == "Asia/Kolkata"
    assert s.browser_geolocation == "19.0760,72.8777"
