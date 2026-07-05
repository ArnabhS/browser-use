import pytest

from app.browser.local_cdp import LocalCDPSession

pytestmark = pytest.mark.browser

_HTML = "<button style='position:absolute;top:50px;left:50px;width:80px;height:30px'>Go</button>"


async def test_marks_are_composited_server_side_never_touching_the_dom():
    sess = LocalCDPSession(draw_som_overlay=True)
    await sess.start()
    try:
        await sess.page.set_content(_HTML)
        obs = await sess.observe()
        assert obs.elements and sess.latest_screenshot and len(sess.latest_screenshot) > 100
        # Marks are drawn onto the image in Python, so the live page never gets an overlay node
        # (no flashing boxes in the user's real browser).
        residue = await sess.page.evaluate("() => !!document.getElementById('__som_overlay__')")
        assert residue is False
        assert sess.latest_screenshot[:2] == b"\xff\xd8"   # JPEG magic — composited + compressed
    finally:
        await sess.stop()


async def test_overlay_changes_the_screenshot_bytes():
    on = LocalCDPSession(draw_som_overlay=True)
    off = LocalCDPSession(draw_som_overlay=False)
    await on.start()
    await off.start()
    try:
        await on.page.set_content(_HTML)
        await off.page.set_content(_HTML)
        await on.observe()
        await off.observe()
        assert on.latest_screenshot != off.latest_screenshot   # the boxes altered the image
    finally:
        await on.stop()
        await off.stop()
