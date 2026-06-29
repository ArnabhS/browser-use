"""Tabs get a STABLE per-session id (not a positional index), so the agent can say
'go back to tab 0' even after another tab closed and the live page order shifted."""
from app.browser.tab_registry import TabRegistry


class _FakePage:
    def __init__(self) -> None:
        self._closed = False

    def is_closed(self) -> bool:
        return self._closed


def test_assigns_stable_monotonic_ids():
    r = TabRegistry()
    a, b = _FakePage(), _FakePage()
    assert r.register(a) == 0
    assert r.register(b) == 1
    assert r.register(a) == 0  # same page object → same id, every time


def test_closed_tab_id_is_not_reused():
    r = TabRegistry()
    a, b = _FakePage(), _FakePage()
    r.register(a)              # 0
    r.register(b)              # 1
    a._closed = True
    r.sync([b])               # prune the closed tab
    c = _FakePage()
    assert r.register(c) == 2  # fresh id — never recycles 0


def test_page_for_resolves_id_to_live_page():
    r = TabRegistry()
    a, b = _FakePage(), _FakePage()
    r.register(a)
    r.register(b)
    assert r.page_for(1, [a, b]) is b
    assert r.page_for(0, [a, b]) is a
    assert r.page_for(99, [a, b]) is None  # unknown id → None, never raises


def test_sync_registers_newly_seen_pages():
    r = TabRegistry()
    a, b = _FakePage(), _FakePage()
    r.sync([a, b])             # both seen for the first time here
    assert r.id_of(a) == 0 and r.id_of(b) == 1
