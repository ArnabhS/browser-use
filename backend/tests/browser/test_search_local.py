"""P0-4 parity: search_page / find_elements must also work on the DEFAULT LocalCDPSession backend,
not only the new CDP one (they share the JS)."""
import urllib.parse

import pytest
from browser_agent_contracts import ActionCall

from app.browser.local_cdp import LocalCDPSession

pytestmark = pytest.mark.browser

_FIXTURE = "data:text/html," + urllib.parse.quote(
    "<button id='a'>Alpha</button><button id='b'>Reveal</button>"
)


async def test_local_cdp_search_and_find():
    s = LocalCDPSession(headless=True)
    await s.start()
    try:
        await s.navigate(_FIXTURE)
        hit = await s.act(ActionCall(name="search_page", args={"pattern": "Reveal"}))
        assert hit.success and "Reveal" in hit.reason
        miss = await s.act(ActionCall(name="search_page", args={"pattern": "zzz-none"}))
        assert "no matches" in miss.reason
        found = await s.act(ActionCall(name="find_elements",
                                       args={"selector": "button", "attributes": ["id"]}))
        assert found.success and "id='a'" in found.reason
    finally:
        await s.stop()
