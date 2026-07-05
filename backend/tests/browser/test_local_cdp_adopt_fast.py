"""_adopt_new_tab polled up to 3s after EVERY click — but ~99% of clicks open no tab, so that was
a flat 3s tax per click (profiled: 3.03s). A click that isn't on a target=_blank link must not
poll: any surprise tab (window.open) is still picked up by the lazy _follow_unseen_tab on the next
observe. Only a _blank link waits, and only briefly."""
import time

import pytest

from app.browser.local_cdp import LocalCDPSession


class _Ctx:
    pages: list = []


class _Page:
    context = _Ctx()

    def is_closed(self):
        return False


@pytest.mark.asyncio
async def test_adopt_without_tab_expectation_returns_immediately():
    sess = LocalCDPSession()
    sess._page = _Page()

    t = time.monotonic()
    followed = await sess._adopt_new_tab(set(), expect_tab=False)
    elapsed = time.monotonic() - t

    assert followed is False
    assert elapsed < 0.3   # no 3s poll — was ~3.0s before
