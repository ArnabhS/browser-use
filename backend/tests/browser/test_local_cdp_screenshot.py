"""The vision/live-view screenshot must be fast AND crash-proof. Playwright's page.screenshot()
blocks on fonts + paint-stability and hangs on animation-heavy sites (metacritic timed out every
single turn, starving the task of its budget), so we capture via CDP Page.captureScreenshot — which
grabs the frame immediately — and keep the previous frame on any failure instead of crashing."""
import base64

from app.browser.local_cdp import LocalCDPSession


class _OkCDP:
    async def send(self, method, params):
        assert method == "Page.captureScreenshot"
        return {"data": base64.b64encode(b"PNGBYTES").decode()}


class _RaisingCDP:
    async def send(self, *_a, **_k):
        raise TimeoutError("captureScreenshot timed out")


async def test_screenshot_uses_cdp_capture_not_playwright():
    sess = LocalCDPSession()

    async def _fake_cdp():
        return _OkCDP()

    sess._cdp_session = _fake_cdp
    assert await sess._safe_screenshot() == b"PNGBYTES"   # decoded CDP frame, no font/stability wait


async def test_screenshot_failure_is_swallowed_and_keeps_previous_frame():
    sess = LocalCDPSession()
    sess.latest_screenshot = b"previous-frame"

    async def _fake_cdp():
        return _RaisingCDP()

    sess._cdp_session = _fake_cdp
    assert await sess._safe_screenshot() == b"previous-frame"   # kept last good frame, didn't raise


async def test_screenshot_failure_drops_cached_cdp_session():
    # A hung captureScreenshot blocks every later command queued on that CDP session — so a failure
    # must drop the cached session, or one stall cascades into every subsequent screenshot timing
    # out (metacritic: 20 back-to-back failures burning the whole budget).
    sess = LocalCDPSession()
    sess._cdp = object()          # pretend a session is cached

    async def _fake_cdp():
        return _RaisingCDP()

    sess._cdp_session = _fake_cdp
    await sess._safe_screenshot()
    assert sess._cdp is None      # dropped so the next capture starts on a fresh session
