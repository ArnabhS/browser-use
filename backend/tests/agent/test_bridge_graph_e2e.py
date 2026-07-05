"""End-to-end proof of the bridge relay: the REAL LangGraph loop drives the REAL
`ExtensionBridgeSession`, whose observe/act requests are answered by a fake extension (a coroutine
servicing the hub). Only the WebSocket bytes are faked — that transport is covered by the /ws/bridge
endpoint test. This is the closest deterministic stand-in for "the agent drives the user's Chrome":
if this passes, the whole pipe (graph → session → hub → extension protocol → back) is wired."""
from __future__ import annotations

import asyncio

from app.agent.demo import run
from app.browser.extension_bridge import BridgeConnection, BridgeHub, ExtensionBridgeSession
from app.config.container import build_default_app
from app.events.sink import BufferSink
from tests.fakes.fake_llm import FakeLLMClient, ai

OBSERVATION = {
    "url": "https://example.test/login",
    "title": "Login",
    "viewport": {"width": 1000, "height": 800},
    "elements": [{"index": 0, "role": "button", "name": "Login"}],
}


async def _fake_extension(sent: asyncio.Queue, conn: BridgeConnection) -> None:
    """Play the role of the extension: answer every request the session sends over the hub."""
    while True:
        env = await sent.get()
        t = env.get("type")
        if t == "observe":
            conn.handle_incoming({"type": "result", "id": env["id"], "payload": OBSERVATION})
        elif t in ("act", "navigate"):
            conn.handle_incoming(
                {"type": "result", "id": env["id"], "payload": {"success": True, "reason": f"{t} ok"}}
            )
        elif t == "tabs":
            conn.handle_incoming({"type": "result", "id": env["id"], "payload": {"tabs": []}})
        else:
            conn.handle_incoming({"type": "result", "id": env["id"], "payload": {}})


async def test_graph_drives_the_bridge_to_completion():
    # A hub + connection whose "socket" just queues outbound envelopes for the fake extension.
    sent: asyncio.Queue = asyncio.Queue()

    async def _send(env: dict) -> None:
        await sent.put(env)

    conn = BridgeConnection(_send)
    hub = BridgeHub()
    hub.set_connection(conn)
    session = ExtensionBridgeSession(hub)
    await session.start()

    ext = asyncio.create_task(_fake_extension(sent, conn))

    llm = FakeLLMClient(
        turns=[
            ai("I'll click Login", [{"name": "Click", "args": {"index": 0}, "id": "a"}]),
            ai("All done", [{"name": "Complete", "args": {"success": True, "reason": "logged in"}, "id": "b"}]),
        ]
    )
    sink = BufferSink()
    graph, emitter, store, _sink, memory = build_default_app(session=session, llm=llm, sink=sink)

    try:
        final = await run(graph, task="log in", thread_id="bridge-e2e", emitter=emitter, memory=memory)
    finally:
        ext.cancel()

    assert final.success is True
    assert final.reason == "logged in"

    events = {e.event for e in sink.events}
    assert "tool_call" in events  # the Click was dispatched over the bridge
    assert "finalize" in events
    # and the click really round-tripped as an ActionCall named "click"
    assert final.last_action is not None and final.last_action.name == "click"
    assert final.last_result is not None and final.last_result.success is True
