"""Anti-bot pages (PerimeterX — e.g. Skyscanner's captcha) plant elements with a BROKEN prototype
chain: every property (tagName, nodeName, outerHTML…) reads undefined, so naive DOM crawlers crash.
Our extractor died mid-`observe` with `Cannot read properties of undefined (reading 'toLowerCase')`,
killing the whole run. A pathological element must be skipped — never fatal — and the rest of the
page must still be extracted (the agent needs to SEE the captcha page to tell the user about it)."""
import pytest

from app.browser.local_cdp import LocalCDPSession

pytestmark = pytest.mark.browser


async def test_prototype_nuked_element_does_not_kill_observe():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content(
            "<button style='width:120px;height:36px'>Real button</button><iframe id='trap'></iframe>"
        )
        # Reproduce the PerimeterX trap: break the element's prototype chain so tagName reads
        # undefined (exactly what Skyscanner's captcha page does).
        await sess.page.evaluate(
            "() => { Object.setPrototypeOf(document.getElementById('trap'), null); }"
        )
        obs = await sess.observe()  # must not raise
        names = [(e.name or "") for e in obs.elements]
        assert any("Real button" in n for n in names), names
    finally:
        await sess.stop()
