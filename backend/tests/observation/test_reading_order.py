from app.observation.funnel.som import IndexedElement
from app.observation.funnel.reading_order import ReadingOrderFormatter


def _ie(index, x, y, in_vp=True, name="b"):
    return IndexedElement(tag="button", role="button", name=name, value=None,
                          x=x, y=y, width=10, height=10, visible=True, in_viewport=in_vp,
                          index=index, center_x=x + 5, center_y=y + 5)


def test_reading_order_sorts_top_then_left_keeps_indices():
    items = [_ie(1, 100, 200), _ie(2, 10, 10), _ie(3, 90, 10)]
    elements, dropped = ReadingOrderFormatter().apply(items)
    # row y=10 first (left-to-right: index 2 then 3), then y=200 (index 1)
    assert [e.index for e in elements] == [2, 3, 1]
    assert dropped == 0


def test_reading_order_budget_drops_offscreen_first_and_counts():
    items = [_ie(1, 0, 0, in_vp=True), _ie(2, 0, 50, in_vp=False), _ie(3, 0, 100, in_vp=True)]
    elements, dropped = ReadingOrderFormatter(max_elements=2).apply(items)
    kept = {e.index for e in elements}
    assert kept == {1, 3} and dropped == 1   # the off-screen one (2) is dropped
