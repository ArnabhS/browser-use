"""The funnel trace must pinpoint WHICH stage drops an element the agent can see but
can't act on (e.g. a fixed 'Add to cart' bar) — extracted-then-dropped vs never-extracted."""
from app.observation.funnel.trace import trace_funnel
from app.observation.raw import RawElement


def _el(name, **kw):
    d = dict(tag="div", role="button", name=name, x=0, y=0, width=10, height=10)
    d.update(kw)
    return RawElement(**d)


def test_trace_reports_the_stage_where_a_focus_element_is_dropped():
    cart = _el("ADD TO CART", tag="button")
    other = _el("Home", tag="a")
    stages = [
        ("extract", [cart, other]),
        ("visibility", [cart, other]),
        ("occlusion", [other]),            # cart dropped here
        ("wrapper_collapse", [other]),
    ]
    blob = "\n".join(trace_funnel(stages, focus="add to cart"))
    assert "extract: 2 elements" in blob
    assert "focus 'add to cart': 1" in blob          # it WAS extracted
    assert "DROPPED at occlusion" in blob            # ...and died at occlusion
    assert "ADD TO CART" in blob


def test_trace_flags_a_focus_term_that_was_never_extracted():
    stages = [
        ("extract", [_el("Home", tag="a")]),
        ("visibility", [_el("Home", tag="a")]),
    ]
    blob = "\n".join(trace_funnel(stages, focus="cart"))
    assert "focus 'cart': 0" in blob                 # not in the interactive set at all
    assert "DROPPED" not in blob                      # nothing to drop — it was never there
