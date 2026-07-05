"""A trusted click on some links (search-result cards, JS-routed anchors that preventDefault)
fires but never navigates — the agent then re-clicks the same dead index until the loop guard
trips (seen on bbcgoodfood 'Keto pancakes' and metacritic show links). When a click lands on a
real hyperlink but the page doesn't move, the session must follow the anchor's href."""
import pytest

from app.browser.local_cdp import LocalCDPSession, _navigable_href
from browser_agent_contracts import ActionCall


def test_navigable_href_accepts_cross_page_http():
    assert _navigable_href("https://x.com/dest", "https://x.com/search") == "https://x.com/dest"


def test_navigable_href_rejects_same_page_and_fragments():
    # Same page (an in-page #anchor or a no-op link) is not a navigation.
    assert _navigable_href("https://x.com/p", "https://x.com/p") is None
    assert _navigable_href("https://x.com/p#sec", "https://x.com/p") is None


def test_navigable_href_rejects_non_http_and_empty():
    assert _navigable_href(None, "https://x.com/") is None
    assert _navigable_href("javascript:void(0)", "https://x.com/") is None
    assert _navigable_href("mailto:a@b.com", "https://x.com/") is None
    assert _navigable_href("", "https://x.com/") is None


@pytest.mark.browser
async def test_click_on_link_that_blocks_nav_follows_href():
    sess = LocalCDPSession()
    await sess.start()
    try:
        # The destination is served locally so the test is deterministic and offline.
        await sess.page.route(
            "**/recipe",
            lambda route: route.fulfill(
                status=200, content_type="text/html", body="<h1>RECIPE PAGE</h1>"
            ),
        )
        # A real anchor whose click is swallowed by JS (onclick preventDefault) — a trusted click
        # reaches it but nothing navigates, exactly like the looping search-result links.
        await sess.page.set_content(
            '<a href="https://example.com/recipe" onclick="event.preventDefault()" '
            'style="font-size:40px;display:block;padding:40px">Keto pancakes</a>'
        )
        obs = await sess.observe()
        link = next(e for e in obs.elements if "keto" in (e.name or "").lower())

        result = await sess.act(ActionCall(name="click", args={"index": link.index}))

        assert "example.com/recipe" in sess.page.url          # followed the href
        assert "RECIPE PAGE" in await sess.page.inner_text("body")
        assert result.success
    finally:
        await sess.stop()


@pytest.mark.browser
async def test_click_on_plain_button_does_not_navigate():
    """The fallback must NOT fire for a non-link click that legitimately does nothing on the URL."""
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content('<button style="font-size:30px">Just a button</button>')
        url_before = sess.page.url
        obs = await sess.observe()
        btn = next(e for e in obs.elements if "button" in (e.name or "").lower())
        await sess.act(ActionCall(name="click", args={"index": btn.index}))
        assert sess.page.url == url_before                   # no href → stayed put
    finally:
        await sess.stop()
