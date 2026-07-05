"""Milestone 1a — the backend half of the bridge.

`ExtensionBridgeSession` is a `BrowserSession` that drives the user's real Chrome by relaying
observe/act/navigate/tabs over a WebSocket to the extension. These unit tests use a *fake bridge
socket* (a list that records outbound envelopes) and hand-feed the replies the extension would send,
so the whole relay is exercised without any browser or real socket."""
from __future__ import annotations

import asyncio

import pytest
from browser_agent_contracts import ActionCall, Tab, Viewport

from app.browser.extension_bridge import (
    BridgeConnection,
    BridgeHub,
    ExtensionBridgeSession,
)


def _make(default_timeout: float = 5.0):
    """A hub with one connection whose `send` records outbound envelopes into `sent`."""
    sent: list[dict] = []

    async def _send(env: dict) -> None:
        sent.append(env)

    hub = BridgeHub()
    conn = BridgeConnection(_send, default_timeout=default_timeout)
    hub.set_connection(conn)
    return hub, conn, sent


async def _reply_to_last(sent: list[dict], conn: BridgeConnection, mtype: str, payload: dict):
    """Wait until a request envelope has been sent, then feed the matching reply by echoing its id."""
    for _ in range(1000):
        if sent:
            break
        await asyncio.sleep(0)
    env = sent[-1]
    conn.handle_incoming({"type": mtype, "id": env["id"], "payload": payload})
    return env


# --------------------------------------------------------------------------- observe / act


async def test_observe_sends_request_and_parses_observation():
    hub, conn, sent = _make()
    session = ExtensionBridgeSession(hub)
    obs_payload = {
        "url": "https://example.com",
        "title": "Example",
        "viewport": {"width": 1280, "height": 800},
        "elements": [{"index": 0, "role": "button", "name": "Go"}],
    }
    task = asyncio.create_task(session.observe(include_som=True))
    env = await _reply_to_last(sent, conn, "result", obs_payload)
    obs = await task

    assert env["type"] == "observe"
    assert env["payload"] == {"includeSom": True}
    assert env["id"]  # a correlation id was assigned
    assert obs.url == "https://example.com"
    assert obs.elements[0].name == "Go"


async def test_act_correlates_id_and_returns_result():
    hub, conn, sent = _make()
    session = ExtensionBridgeSession(hub)
    task = asyncio.create_task(session.act(ActionCall(name="Click", args={"index": 3})))
    env = await _reply_to_last(sent, conn, "result", {"success": True, "reason": "clicked"})
    res = await task

    assert env["type"] == "act"
    assert env["payload"]["name"] == "Click"
    assert env["payload"]["args"] == {"index": 3}
    assert res.success is True
    assert res.reason == "clicked"


async def test_navigate_sends_url_and_returns_result():
    hub, conn, sent = _make()
    session = ExtensionBridgeSession(hub)
    task = asyncio.create_task(session.navigate("https://foo.test"))
    env = await _reply_to_last(sent, conn, "result", {"success": True})
    res = await task
    assert env["type"] == "navigate"
    assert env["payload"] == {"url": "https://foo.test"}
    assert res.success is True


async def test_tabs_parses_tab_list():
    hub, conn, sent = _make()
    session = ExtensionBridgeSession(hub)
    task = asyncio.create_task(session.tabs())
    await _reply_to_last(sent, conn, "result", {"tabs": [{"id": 1, "title": "A", "active": True}]})
    tabs = await task
    assert len(tabs) == 1
    assert isinstance(tabs[0], Tab)
    assert tabs[0].id == 1 and tabs[0].active is True


# --------------------------------------------------------------------------- error paths (typed codes)


async def test_act_timeout_returns_bridge_timeout_code():
    hub, conn, sent = _make(default_timeout=0.05)
    session = ExtensionBridgeSession(hub, act_timeout=0.05)
    res = await session.act(ActionCall(name="Click", args={"index": 1}))  # nobody replies
    assert res.success is False
    assert res.error_code == "BRIDGE_TIMEOUT"


async def test_act_with_no_bridge_connected_returns_disconnected():
    hub = BridgeHub()  # no connection ever set
    session = ExtensionBridgeSession(hub)
    res = await session.act(ActionCall(name="Click", args={"index": 1}))
    assert res.success is False
    assert res.error_code == "BRIDGE_DISCONNECTED"


async def test_error_reply_maps_to_failed_action_result():
    hub, conn, sent = _make()
    session = ExtensionBridgeSession(hub)
    task = asyncio.create_task(session.act(ActionCall(name="Click", args={"index": 9})))
    await _reply_to_last(sent, conn, "error", {"message": "no such element", "errorCode": "NAV_FAILED"})
    res = await task
    assert res.success is False
    assert res.error_code == "NAV_FAILED"
    assert "no such element" in res.reason


async def test_observe_timeout_raises():
    hub, conn, sent = _make(default_timeout=0.05)
    session = ExtensionBridgeSession(hub, observe_timeout=0.05)
    with pytest.raises(Exception):
        await session.observe()


async def test_disconnect_fails_pending_requests():
    hub, conn, sent = _make()
    session = ExtensionBridgeSession(hub)
    task = asyncio.create_task(session.act(ActionCall(name="Click", args={"index": 1})))
    for _ in range(1000):  # let the request go out
        if sent:
            break
        await asyncio.sleep(0)
    conn.fail_all()  # extension socket dropped
    hub.clear_connection(conn)
    res = await task
    assert res.success is False
    assert res.error_code == "BRIDGE_DISCONNECTED"


# --------------------------------------------------------------------------- frames + register


async def test_frame_is_forwarded_to_session_on_frame():
    hub, conn, sent = _make()
    session = ExtensionBridgeSession(hub)
    await session.start()
    got: list[tuple] = []

    async def _on_frame(data_b64: str, meta: dict) -> None:
        got.append((data_b64, meta))

    session.on_frame = _on_frame
    await hub.dispatch_frame("BASE64JPEG", {"url": "https://x.test"})
    assert got == [("BASE64JPEG", {"url": "https://x.test"})]


async def test_register_marks_connection_ready():
    hub, conn, sent = _make()
    conn.handle_incoming({"type": "register", "payload": {"userAgent": "Chrome", "tabId": 7}})
    assert conn.registered is True
    assert conn.info["tabId"] == 7


async def test_stale_reply_is_ignored():
    hub, conn, sent = _make()
    # a reply for an unknown id must not blow up
    conn.handle_incoming({"type": "result", "id": "nope", "payload": {}})
    assert hub.connected is True
