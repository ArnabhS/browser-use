"""The /ws/bridge endpoint (spec §6): the browser extension connects here and registers as "the
browser". This adapter only moves bytes — all correlation/lifecycle lives in `extension_bridge`."""
from __future__ import annotations

from fastapi import WebSocket, WebSocketDisconnect

from app.browser.extension_bridge import HUB, BridgeConnection


async def ws_bridge(websocket: WebSocket) -> None:
    await websocket.accept()

    async def _send(env: dict) -> None:
        await websocket.send_json(env)

    conn = BridgeConnection(_send)
    HUB.set_connection(conn)  # single-user: the one connected extension is the browser
    try:
        while True:
            msg = await websocket.receive_json()
            if msg.get("type") == "frame":
                # Unsolicited live-view JPEG: {data, ...meta}. Forward to the active session.
                payload = msg.get("payload", {}) or {}
                data = payload.get("data", "")
                meta = {k: v for k, v in payload.items() if k != "data"}
                await HUB.dispatch_frame(data, meta)
            else:
                conn.handle_incoming(msg)  # register / result / error → resolves pending requests
    except WebSocketDisconnect:
        pass
    finally:
        conn.fail_all()  # reject any in-flight requests so the run fails typed, not hangs
        HUB.clear_connection(conn)
