"""A control's VISIBLE text is ground truth for the agent (it cross-references the screenshot/SoM
overlay). When a site puts a MISLEADING aria-label on a button whose visible text says something
else — e.g. quashbugs.com's header `<a aria-label="Get Early Access To Automate">Book a Demo</a>` —
the funnel must still name it by its visible text, or the agent can't find the button it's told to
press. Icon/glyph controls with no real visible text keep using their aria-label."""
import pytest

from app.browser.local_cdp import LocalCDPSession

pytestmark = pytest.mark.browser


async def test_visible_text_wins_over_mismatched_aria_label():
    sess = LocalCDPSession()
    await sess.start()
    try:
        # The exact shape found on quashbugs.com's header "Book a Demo" link.
        await sess.page.set_content(
            "<a href='/contact-form' aria-label='Get Early Access To Automate' "
            "style='display:block;width:160px;height:40px'>Book a Demo</a>"
        )
        obs = await sess.observe()
        names = [(e.name or "") for e in obs.elements]
        assert any("Book a Demo" in n for n in names), names
        assert not any("Get Early Access" in n for n in names), names
    finally:
        await sess.stop()


async def test_input_named_by_associated_label():
    """HubSpot/most form builders label inputs with <label for=…>, not placeholder/aria-label —
    without label resolution every form field shows as a blank `input ""` and the agent cannot
    tell firstname from email (seen live on quashbugs.com/contact-form)."""
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content(
            "<label for='fn'>First name</label>"
            "<input id='fn' style='width:200px;height:36px'>"
            "<label>Email <input id='em' style='width:200px;height:36px'></label>"
        )
        obs = await sess.observe()
        names = [(e.name or "") for e in obs.elements]
        assert any("First name" in n for n in names), names   # <label for=…>
        assert any("Email" in n for n in names), names          # wrapping <label>
    finally:
        await sess.stop()


async def test_aria_label_kept_for_icon_only_control():
    sess = LocalCDPSession()
    await sess.start()
    try:
        # Glyph-only button: no real visible words → fall back to the aria-label.
        await sess.page.set_content(
            "<button aria-label='Close' style='width:40px;height:40px'>✕</button>"
        )
        obs = await sess.observe()
        names = [(e.name or "") for e in obs.elements]
        assert any("Close" in n for n in names), names
    finally:
        await sess.stop()
