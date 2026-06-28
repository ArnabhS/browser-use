from app.observation.raw import RawElement
from app.observation.funnel.occlusion import OcclusionCuller


def _el(name, occluded=False):
    return RawElement(tag="button", role="button", name=name, value=None,
                      x=0, y=0, width=10, height=10, visible=True, in_viewport=True, occluded=occluded)


def test_occlusion_drops_covered():
    kept = OcclusionCuller().apply([_el("shown"), _el("covered", occluded=True)])
    assert [e.name for e in kept] == ["shown"]
