from app.observation.raw import RawElement
from app.observation.funnel.wrapper_collapse import WrapperCollapser


def _el(tag, role, x=0, y=0, w=100, h=40, name="n"):
    return RawElement(tag=tag, role=role, name=name, value=None,
                      x=x, y=y, width=w, height=h, visible=True, in_viewport=True)


def test_collapses_near_identical_bounds_prefers_real_tag():
    # a div-wrapper and the real <a> with ~same bounds collapse to the <a>
    raw = [_el("div", "generic", x=10, y=10), _el("a", "link", x=11, y=11), _el("button", "button", x=500, y=500)]
    kept = WrapperCollapser().apply(raw)
    tags = sorted(e.tag for e in kept)
    assert tags == ["a", "button"]   # the div wrapper dropped, the standalone button kept
