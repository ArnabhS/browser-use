from app.observation.raw import RawElement
from app.observation.funnel.som import SoMIndexer


def _el(x, y, w, h):
    return RawElement(tag="button", role="button", name="b", value=None,
                      x=x, y=y, width=w, height=h, visible=True, in_viewport=True)


def test_som_assigns_indices_and_centers():
    out = SoMIndexer().apply([_el(0, 0, 10, 20), _el(100, 50, 40, 40)])
    assert [e.index for e in out] == [1, 2]
    assert (out[0].center_x, out[0].center_y) == (5.0, 10.0)
    assert (out[1].center_x, out[1].center_y) == (120.0, 70.0)
