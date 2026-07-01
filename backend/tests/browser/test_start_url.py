"""A session opens on a configurable home page (Google in prod) so the live view shows something
the instant a run begins — not a blank tab. Default stays blank so tests start hermetically."""
import pytest

from app.browser.local_cdp import LocalCDPSession
from app.config.settings import Settings

pytestmark = pytest.mark.browser


async def test_start_navigates_to_start_url():
    # data: URL keeps the test offline while still exercising the goto-on-start path.
    sess = LocalCDPSession(start_url="data:text/html,<title>Home</title><h1>home</h1>")
    await sess.start()
    try:
        assert sess.page.url.startswith("data:text/html")
        assert "Home" in await sess.page.title()
    finally:
        await sess.stop()


async def test_start_without_start_url_stays_blank():
    sess = LocalCDPSession()  # no start_url → hermetic about:blank
    await sess.start()
    try:
        assert sess.page.url == "about:blank"
    finally:
        await sess.stop()


def test_settings_default_start_url_is_google():
    assert Settings(_env_file=None).start_url == "https://www.google.com"
