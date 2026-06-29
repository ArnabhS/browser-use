"""WebSocket API tests — wire the agent engine to /ws/run via fake browser + LLM."""
from __future__ import annotations

from functools import partial

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from tests.fakes.fake_llm import FakeLLMClient, ai


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _drain(ws, stop: str = "run_complete", limit: int = 200) -> list[dict]:
    """Receive JSON frames until `event == stop` (inclusive) or `limit` reached."""
    collected: list[dict] = []
    for _ in range(limit):
        msg = ws.receive_json()
        collected.append(msg)
        if msg.get("event") == stop:
            break
    return collected


async def _fake_build(sink, *, turns: list):
    """Fake composition root: injects FakeBrowserSession + FakeLLMClient."""
    from app.config.container import build_default_app
    from tests.fakes.fake_browser import FakeBrowserSession

    graph, emitter, store, _s, memory = build_default_app(
        session=FakeBrowserSession(),
        llm=FakeLLMClient(turns=turns),
        sink=sink,
    )

    async def cleanup() -> None:
        pass  # nothing to stop for fake session

    return graph, emitter, memory, cleanup


# ---------------------------------------------------------------------------
# Test 1: events stream and finalize
# ---------------------------------------------------------------------------


def test_events_stream_and_finalize(monkeypatch):
    """Start a run, drain to run_complete; verify reasoning/tool_call and finalize events."""
    turns = [
        ai(
            "I'll click Login to proceed",
            [{"name": "Click", "args": {"index": 1}, "id": "a"}],
        ),
        ai(
            "Logged in; task is done",
            [{"name": "Complete", "args": {"success": True, "reason": "done"}, "id": "b"}],
        ),
    ]

    monkeypatch.setattr("app.api.ws.build_running_app", partial(_fake_build, turns=turns))

    with TestClient(app) as client:
        with client.websocket_connect("/ws/run") as ws:
            ws.send_json({"type": "start", "task": "log in (fake)"})
            events = _drain(ws)

    event_types = {e["event"] for e in events}

    # at least one reasoning or tool_call event must have streamed
    assert event_types & {"reasoning", "tool_call"}, (
        f"expected reasoning or tool_call, got: {event_types}"
    )
    # finalize must be present
    assert "finalize" in event_types, f"missing finalize in: {event_types}"
    # last event in the drain must be run_complete
    assert events[-1]["event"] == "run_complete"


# ---------------------------------------------------------------------------
# Test 2: AskUser round-trip
# ---------------------------------------------------------------------------


def test_ask_user_round_trip(monkeypatch):
    """Agent asks a question; cockpit sends answer; run completes with success=True."""
    turns = [
        ai(
            "I need the OTP to continue",
            [
                {
                    "name": "AskUser",
                    "args": {"question": "OTP?", "context": ""},
                    "id": "q1",
                }
            ],
        ),
        ai(
            "Got the code, finishing now",
            [
                {
                    "name": "Complete",
                    "args": {"success": True, "reason": "used the OTP"},
                    "id": "c1",
                }
            ],
        ),
    ]

    monkeypatch.setattr("app.api.ws.build_running_app", partial(_fake_build, turns=turns))

    with TestClient(app) as client:
        with client.websocket_connect("/ws/run") as ws:
            ws.send_json({"type": "start", "task": "log in with OTP"})

            # drain until the question event
            pre: list[dict] = []
            question_event = None
            for _ in range(200):
                msg = ws.receive_json()
                if msg.get("event") == "question":
                    question_event = msg
                    break
                pre.append(msg)

            assert question_event is not None, "never received a question event"
            assert question_event["data"]["question"] == "OTP?"

            # send the answer back
            ws.send_json({"type": "answer", "answer": "123456"})

            # drain to run_complete
            post = _drain(ws)

    all_events = pre + [question_event] + post
    finalize_events = [e for e in all_events if e["event"] == "finalize"]
    assert finalize_events, "no finalize event found"
    assert finalize_events[-1]["data"]["success"] is True
    assert post[-1]["event"] == "run_complete"


# ---------------------------------------------------------------------------
# Test 3: Stop cancels a running task
# ---------------------------------------------------------------------------


def test_stop_cancels_running_task(monkeypatch):
    """A long-running task can be stopped; the cockpit gets run_complete with stopped=True."""
    import asyncio

    from browser_agent_contracts import ActionResult, Observation, Viewport

    class _SlowVaryingBrowser:
        """Never settles: each observe is a *different* page (so the stuck guard won't end it)."""

        def __init__(self) -> None:
            self.n = 0
            self.latest_screenshot = None

        async def observe(self, *, include_som: bool = True) -> Observation:
            await asyncio.sleep(0.15)
            self.n += 1
            return Observation(url=f"about:blank#{self.n}", title="", viewport=Viewport(width=1280, height=800))

        async def act(self, call) -> ActionResult:
            await asyncio.sleep(0.15)
            return ActionResult(success=True, reason="ok")

        async def navigate(self, url) -> ActionResult:
            return ActionResult(success=True, reason="ok")

        async def tabs(self):
            return []

    turns = [ai("scrolling", [{"name": "Scroll", "args": {"direction": "down"}, "id": f"s{i}"}]) for i in range(60)]

    async def _slow_build(sink):
        from app.config.container import build_default_app

        graph, emitter, store, _s, memory = build_default_app(
            session=_SlowVaryingBrowser(), llm=FakeLLMClient(turns=turns), sink=sink
        )

        async def cleanup() -> None:
            pass

        return graph, emitter, memory, cleanup

    monkeypatch.setattr("app.api.ws.build_running_app", _slow_build)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/run") as ws:
            ws.send_json({"type": "start", "task": "scroll forever"})
            # wait until it is demonstrably running
            for _ in range(60):
                if ws.receive_json().get("event") in {"observation", "reasoning", "tool_call"}:
                    break
            ws.send_json({"type": "stop"})
            final = None
            for _ in range(200):
                msg = ws.receive_json()
                if msg.get("event") == "run_complete":
                    final = msg
                    break

    assert final is not None, "never received run_complete after stop"
    assert final["data"].get("stopped") is True
