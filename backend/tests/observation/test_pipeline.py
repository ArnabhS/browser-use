from app.observation.raw import RawElement, PageMeta
from app.observation.funnel.pipeline import run_funnel


def _el(name, x, y, visible=True):
    return RawElement(tag="button", role="button", name=name, value=None,
                      x=x, y=y, width=10, height=10, visible=visible, in_viewport=True)


def test_pipeline_builds_observation_and_index_map():
    meta = PageMeta(url="https://x", title="X", viewport_width=1280, viewport_height=800)
    raw = [_el("Login", 10, 10), _el("hidden", 0, 0, visible=False), _el("Email", 10, 40)]
    obs, index_map = run_funnel(raw, meta, screenshot_ref="s1")
    assert obs.url == "https://x" and obs.title == "X" and obs.screenshot_ref == "s1"
    assert [e.name for e in obs.elements] == ["Login", "Email"]          # hidden dropped
    assert [e.index for e in obs.elements] == [1, 2]
    assert index_map[1] == (15.0, 15.0) and index_map[2] == (15.0, 45.0)  # click centers
    assert obs.dropped_count == 0
    # contract guarantee: no coordinates leak into the Observation elements
    assert not any(hasattr(e, "center_x") for e in obs.elements)
