from app.observation.raw import RawElement, PageMeta
from app.observation.funnel.pipeline import run_funnel


def _el(name, x, y, visible=True):
    return RawElement(tag="button", role="button", name=name, value=None,
                      x=x, y=y, width=10, height=10, visible=visible, in_viewport=True)


def test_pipeline_builds_observation_and_index_map():
    meta = PageMeta(url="https://x", title="X", viewport_width=1280, viewport_height=800)
    raw = [_el("Login", 10, 10), _el("hidden", 0, 0, visible=False), _el("Email", 10, 40)]
    obs, index_map, index_boxes = run_funnel(raw, meta, screenshot_ref="s1")
    assert obs.url == "https://x" and obs.title == "X" and obs.screenshot_ref == "s1"
    assert [e.name for e in obs.elements] == ["Login", "Email"]          # hidden dropped
    assert [e.index for e in obs.elements] == [1, 2]
    assert index_map[1] == (15.0, 15.0) and index_map[2] == (15.0, 45.0)  # click centers
    assert obs.dropped_count == 0
    # contract guarantee: no coordinates leak into the Observation elements
    assert not any(hasattr(e, "center_x") for e in obs.elements)
    assert index_boxes[1] == (10.0, 10.0, 10.0, 10.0)
    assert set(index_boxes) == set(index_map)


def test_pipeline_drops_occluded_and_collapses_wrappers():
    from app.observation.raw import RawElement, PageMeta
    from app.observation.funnel.pipeline import run_funnel
    meta = PageMeta(url="https://x", viewport_width=800, viewport_height=600)
    raw = [
        RawElement(tag="a", role="link", name="Real", value=None, x=10, y=10, width=100, height=30,
                   visible=True, in_viewport=True, occluded=False),
        RawElement(tag="div", role="generic", name="Wrapper", value=None, x=11, y=11, width=100, height=30,
                   visible=True, in_viewport=True, occluded=False),                 # collapses into Real
        RawElement(tag="button", role="button", name="Covered", value=None, x=10, y=200, width=100, height=30,
                   visible=True, in_viewport=True, occluded=True),                  # occluded → dropped
    ]
    obs, index_map, index_boxes = run_funnel(raw, meta, screenshot_ref="s")
    names = [e.name for e in obs.elements]
    assert "Covered" not in names and "Wrapper" not in names and "Real" in names
    assert set(index_map.keys()) == {e.index for e in obs.elements}
