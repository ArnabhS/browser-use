import pytest
from app.browser.local_cdp import LocalCDPSession
from app.browser.base import BrowserSession
from browser_agent_contracts import Observation

pytestmark = pytest.mark.browser

_HTML = "<html><head><title>T</title></head><body><button>Go</button><input placeholder='Q'></body></html>"


async def test_observe_returns_numbered_observation():
    sess = LocalCDPSession()
    await sess.start()
    try:
        assert isinstance(sess, BrowserSession)
        await sess.page.set_content(_HTML)
        obs = await sess.observe()
        assert isinstance(obs, Observation) and obs.title == "T"
        names = {e.name for e in obs.elements}
        assert "Go" in names and "Q" in names
        assert sess.latest_screenshot is not None and obs.screenshot_ref is not None
        assert set(sess.index_map.keys()) == {e.index for e in obs.elements}
    finally:
        await sess.stop()
