"""window.scrollY/scrollX are fractional on hi-DPI / zoomed / very long pages (e.g. 10129.5).
PageMeta must coerce them to int instead of crashing extraction mid-task."""
from app.observation.raw import PageMeta


def test_page_meta_coerces_fractional_scroll_to_int():
    m = PageMeta(
        url="https://x.com", viewport_width=1280, viewport_height=720,
        scroll_x=8.9, scroll_y=10129.3,
    )
    assert isinstance(m.scroll_y, int) and m.scroll_y == 10129
    assert isinstance(m.scroll_x, int) and m.scroll_x == 9
