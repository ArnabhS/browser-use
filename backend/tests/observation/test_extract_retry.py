"""extract() must survive a navigation tearing down the JS context mid-evaluate."""
import pytest

from app.observation.extract import extract

_PAGE_DATA = {
    "url": "https://x/", "title": "T",
    "viewport_width": 800, "viewport_height": 600,
    "scroll_x": 0, "scroll_y": 0, "elements": [],
}


class _FakePage:
    def __init__(self, fail_times: int) -> None:
        self._fail_times = fail_times
        self.evaluate_calls = 0

    async def wait_for_load_state(self, *a, **k):
        return None

    async def evaluate(self, _js):
        self.evaluate_calls += 1
        if self.evaluate_calls <= self._fail_times:
            raise RuntimeError("Execution context was destroyed, most likely because of a navigation")
        return _PAGE_DATA


async def test_extract_retries_on_navigation_then_succeeds():
    page = _FakePage(fail_times=1)
    raw, meta = await extract(page)
    assert page.evaluate_calls == 2          # retried once after the destroyed context
    assert meta.url == "https://x/" and raw == []


async def test_extract_reraises_after_exhausting_retries():
    page = _FakePage(fail_times=99)          # page never stops navigating
    with pytest.raises(Exception) as ei:
        await extract(page, retries=3)
    assert "execution context was destroyed" in str(ei.value).lower()
    assert page.evaluate_calls == 3          # exactly `retries` attempts


async def test_extract_reraises_non_navigation_errors_immediately():
    class _Boom:
        async def wait_for_load_state(self, *a, **k):
            return None

        async def evaluate(self, _js):
            raise ValueError("an unrelated bug")

    with pytest.raises(ValueError):
        await extract(_Boom())
