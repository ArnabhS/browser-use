"""Integration: the /ws/bridge endpoint registers the extension into the hub, forwards frames to
the active session, and cleans up on disconnect. The full observe/act round-trip over two sockets is
covered by the manual real-Chrome acceptance run; here we pin the endpoint's own responsibilities."""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.api.main import app
from app.browser.extension_bridge import HUB


def _wait(pred, tries: int = 100) -> None:
    for _ in range(tries):
        if pred():
            return
        time.sleep(0.02)


def test_bridge_registers_forwards_frames_and_cleans_up():
    frames: list[tuple] = []

    async def _rec(data: str, meta: dict) -> None:
        frames.append((data, meta))

    HUB.on_frame = _rec
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/ws/bridge") as ext:
                # endpoint registers the connection into the hub on accept
                _wait(lambda: HUB.connected)
                assert HUB.connected is True

                ext.send_json({"type": "register", "payload": {"userAgent": "UA", "tabId": 2}})
                ext.send_json({"type": "frame", "payload": {"data": "B64JPEG", "url": "https://x.test"}})
                _wait(lambda: len(frames) > 0)

            # left the `with` — extension socket closed
            _wait(lambda: not HUB.connected)
    finally:
        HUB.on_frame = None

    assert frames, "frame was not forwarded to the active session"
    assert frames[0][0] == "B64JPEG"
    assert frames[0][1] == {"url": "https://x.test"}  # meta excludes the data field
    assert HUB.connected is False, "hub must clear the connection on disconnect"
