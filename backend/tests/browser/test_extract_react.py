"""React/React-Native-Web build their controls as plain <div>s with NO role/cursor/tabindex/
onclick — the click handler lives only in React's props, stashed on the DOM node under a
`__reactProps$…` key. The extractor must detect that, or buttons like Flipkart's 'Add to cart'
are invisible to the agent (it can SEE them but they never enter the element list)."""
import pytest

from app.browser.local_cdp import LocalCDPSession
from browser_agent_contracts import ActionCall  # noqa: F401  (kept for parity with sibling tests)

pytestmark = pytest.mark.browser


async def test_extracts_react_div_button_via_fiber_props():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content(
            "<div id='plain' style='width:140px;height:40px'>Just a label</div>"
            "<div id='btn' style='width:140px;height:40px'>Add to cart</div>"
        )
        # Reproduce exactly what React 17+ does: attach the component props (incl. the click
        # handler) to the DOM node under a __reactProps$<hash> key. No role/cursor/onclick.
        await sess.page.evaluate(
            "() => { document.getElementById('btn')['__reactProps$x'] = { onClick: () => {} }; }"
        )
        obs = await sess.observe()
        names = [(e.name or "").lower() for e in obs.elements]
        assert any("add to cart" in n for n in names)      # the React div-button is extracted
        assert not any("just a label" in n for n in names)  # a plain div is still ignored


    finally:
        await sess.stop()
