"""The model saw `[N] role "name" = value` but never the element's STATE — so it couldn't tell a
checked checkbox from an unchecked one, an expanded menu from a collapsed one, or a disabled button.
Surface checked/expanded/collapsed/selected/disabled in the value field."""
import pytest

from app.browser.local_cdp import LocalCDPSession

pytestmark = pytest.mark.browser


def _val(obs, needle):
    el = next(e for e in obs.elements if needle in (e.name or "").lower())
    return (el.value or "").lower()


async def test_state_surfaces_checked_expanded_disabled():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content(
            "<label><input type=checkbox checked> Accept terms</label>"
            "<button aria-expanded='false' style='font-size:20px'>Filters</button>"
            "<button disabled style='font-size:20px'>Submit order</button>"
            "<div role='tab' aria-selected='true' tabindex='0' style='font-size:20px'>Details</div>"
        )
        obs = await sess.observe()
        assert "checked" in _val(obs, "accept terms")
        assert "collapsed" in _val(obs, "filters")     # aria-expanded=false
        assert "disabled" in _val(obs, "submit order")
        assert "selected" in _val(obs, "details")
    finally:
        await sess.stop()
