"""Multi-tab is now explicit: the observation carries a STABLE tab table, the agent can
peek a tab without switching (observe_tab) and open a link in a background tab
(open_in_new_tab) — instead of us silently swapping the active page under it."""
import pytest

from app.browser.local_cdp import LocalCDPSession
from browser_agent_contracts import ActionCall

pytestmark = pytest.mark.browser


async def test_observe_populates_stable_tab_table():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content("<title>T0</title><body>zero</body>")
        await sess.act(ActionCall(name="new_tab", args={"url": "data:text/html,<title>T1</title>"}))
        obs = await sess.observe()
        assert [t.id for t in obs.tabs] == [0, 1]
        active = [t for t in obs.tabs if t.active]
        assert len(active) == 1 and active[0].id == 1   # the tab we just opened is active
    finally:
        await sess.stop()


async def test_tabs_reports_stable_ids_and_active_flag():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content("<title>T0</title>")
        await sess.act(ActionCall(name="new_tab", args={"url": "data:text/html,<title>T1</title>"}))
        tabs = await sess.tabs()
        assert [t.id for t in tabs] == [0, 1]
        assert [t.active for t in tabs] == [False, True]
    finally:
        await sess.stop()


async def test_observe_tab_peeks_without_switching_focus():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content("<title>HOME</title>")
        await sess.act(ActionCall(name="new_tab", args={"url": "data:text/html,<title>OTHER</title>"}))
        focus_before = sess.page                     # active is tab 1 (OTHER)
        res = await sess.act(ActionCall(name="observe_tab", args={"target_id": "0"}))
        assert res.success and "HOME" in res.reason
        assert sess.page is focus_before             # peeking did NOT move focus
    finally:
        await sess.stop()


async def test_open_in_new_tab_backgrounds_link_without_switching():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content(
            '<a href="data:text/html,<title>OPENED</title>" '
            'style="font-size:40px;display:block;padding:30px">LINK</a>'
        )
        obs = await sess.observe()
        link = next(e for e in obs.elements if "link" in (e.name or "").lower())
        home = sess.page
        res = await sess.act(ActionCall(name="open_in_new_tab", args={"index": link.index}))
        assert res.success
        assert sess.page is home                     # stayed on the original tab
        await sess.observe()                          # next observe must NOT auto-follow it
        assert sess.page is home
        assert len([p for p in home.context.pages if not p.is_closed()]) >= 2
    finally:
        await sess.stop()
