from app.observation.raw import RawElement
from app.observation.funnel.visibility import VisibilityFilter


def _el(**kw):
    base = dict(tag="button", role="button", name="x", value=None,
                x=0, y=0, width=10, height=10, visible=True, in_viewport=True)
    base.update(kw)
    return RawElement(**base)


def test_visibility_drops_hidden_and_zero_size():
    raw = [_el(name="ok"), _el(name="hidden", visible=False), _el(name="zero", width=0)]
    kept = VisibilityFilter().apply(raw)
    assert [e.name for e in kept] == ["ok"]
