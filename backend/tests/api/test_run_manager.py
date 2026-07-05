"""Milestone 1b — run survival across cockpit reconnect.

The run must outlive any single cockpit WebSocket: a refresh detaches the *view* (sink) but must
NOT cancel the run or tear down the browser. On reconnect the cockpit replays buffered events and
resumes live. These unit tests exercise that decoupling without any real socket."""
from __future__ import annotations

import asyncio

import pytest

from app.api.run_manager import FanoutSink, RunManager, RunSession
from app.events.protocol import AgentEvent


def _ev(name: str, **data) -> AgentEvent:
    return AgentEvent(event=name, data=data)


class _Recorder:
    """A fake socket send: records every dict it is handed."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def __call__(self, payload: dict) -> None:
        self.sent.append(payload)


# --------------------------------------------------------------------------- FanoutSink


async def test_buffers_events_with_no_sink_attached():
    fan = FanoutSink()
    await fan.emit(_ev("status", phase="observe"))
    await fan.emit(_ev("reasoning", text="hi"))
    assert fan.attached is False  # nobody watching yet


async def test_attach_replays_buffered_history_in_order():
    fan = FanoutSink()
    await fan.emit(_ev("status", phase="a"))
    await fan.emit(_ev("status", phase="b"))
    rec = _Recorder()
    await fan.attach(rec)
    assert [p["data"]["phase"] for p in rec.sent] == ["a", "b"]
    assert fan.attached is True


async def test_forwards_live_events_after_attach():
    fan = FanoutSink()
    rec = _Recorder()
    await fan.attach(rec)
    await fan.emit(_ev("reasoning", text="live"))
    assert rec.sent[-1]["data"]["text"] == "live"


async def test_detach_stops_forwarding_but_keeps_buffering():
    fan = FanoutSink()
    rec = _Recorder()
    await fan.attach(rec)
    await fan.emit(_ev("status", phase="seen"))
    await fan.detach(rec)
    assert fan.attached is False
    await fan.emit(_ev("status", phase="missed"))
    # the detached recorder never saw the post-detach event...
    assert [p["data"]["phase"] for p in rec.sent] == ["seen"]
    # ...but it was still buffered for the next viewer
    rec2 = _Recorder()
    await fan.attach(rec2)
    assert [p["data"]["phase"] for p in rec2.sent] == ["seen", "missed"]


async def test_reconnect_replays_full_history_including_events_missed_while_gone():
    fan = FanoutSink()
    await fan.emit(_ev("status", phase="a"))
    rec1 = _Recorder()
    await fan.attach(rec1)          # replays a
    await fan.emit(_ev("status", phase="b"))  # rec1 live
    await fan.detach(rec1)
    await fan.emit(_ev("status", phase="c"))  # nobody attached
    rec2 = _Recorder()
    await fan.attach(rec2)          # must replay a, b, c
    assert [p["data"]["phase"] for p in rec2.sent] == ["a", "b", "c"]


async def test_stale_detach_does_not_evict_a_newer_sink():
    """If sink1 detaches AFTER sink2 already attached, sink2 must remain live."""
    fan = FanoutSink()
    rec1 = _Recorder()
    rec2 = _Recorder()
    await fan.attach(rec1)
    await fan.attach(rec2)          # rec2 is now the live target
    await fan.detach(rec1)          # stale detach — must be a no-op
    assert fan.attached is True
    await fan.emit(_ev("status", phase="x"))
    assert rec2.sent[-1]["data"]["phase"] == "x"


async def test_buffer_is_bounded():
    fan = FanoutSink(buffer_size=3)
    for i in range(10):
        await fan.emit(_ev("status", phase=str(i)))
    rec = _Recorder()
    await fan.attach(rec)
    # only the last 3 survive
    assert [p["data"]["phase"] for p in rec.sent] == ["7", "8", "9"]


# --------------------------------------------------------------------------- RunSession


async def test_stop_cancels_task_and_runs_cleanup():
    stopped = {"cleanup": False}

    async def _forever():
        await asyncio.sleep(100)

    async def _cleanup():
        stopped["cleanup"] = True

    rs = RunSession("t1")
    task = asyncio.create_task(_forever())
    rs.bind(task, _cleanup)
    await rs.stop()
    assert task.cancelled() or task.done()
    assert stopped["cleanup"] is True


async def test_detach_does_not_cancel_the_run_task():
    """The heart of run-survival: detaching the view must leave the task running."""
    async def _forever():
        await asyncio.sleep(100)

    rs = RunSession("t1")
    task = asyncio.create_task(_forever())
    rs.bind(task, None)
    rec = _Recorder()
    await rs.attach(rec)
    await rs.detach(rec)
    assert not task.done(), "detach must NOT cancel the run"
    task.cancel()  # cleanup


async def test_answer_provider_delivers_queued_answers():
    rs = RunSession("t1")
    await rs.answer("42")
    got = await rs.answer_provider({"question": "?"})
    assert got == "42"


# --------------------------------------------------------------------------- RunManager


async def test_create_and_get():
    mgr = RunManager()
    rs = await mgr.create("thread-a")
    assert isinstance(rs, RunSession)
    assert mgr.get("thread-a") is rs
    assert mgr.get("nope") is None


async def test_gc_removes_terminal_unattached_after_ttl():
    clock = {"t": 1000.0}
    mgr = RunManager(ttl_seconds=60.0, time_fn=lambda: clock["t"])
    rs = await mgr.create("t1")
    rs.bind(asyncio.create_task(asyncio.sleep(0)), None)
    mgr.mark_done("t1", {"success": True, "reason": "done"})
    # within TTL, no attached sink → survives
    clock["t"] = 1030.0
    await mgr.gc()
    assert mgr.get("t1") is rs
    # past TTL, still unattached → collected
    clock["t"] = 1100.0
    await mgr.gc()
    assert mgr.get("t1") is None


async def test_gc_keeps_attached_terminal_run():
    clock = {"t": 0.0}
    mgr = RunManager(ttl_seconds=1.0, time_fn=lambda: clock["t"])
    rs = await mgr.create("t1")
    rs.bind(asyncio.create_task(asyncio.sleep(0)), None)
    await rs.attach(_Recorder())          # a viewer is watching
    mgr.mark_done("t1", {"success": True, "reason": "done"})
    clock["t"] = 100.0
    await mgr.gc()
    assert mgr.get("t1") is rs, "an attached run must never be GC'd"


async def test_gc_keeps_running_unattached_run():
    clock = {"t": 0.0}
    mgr = RunManager(ttl_seconds=1.0, time_fn=lambda: clock["t"])
    rs = await mgr.create("t1")
    rs.bind(asyncio.create_task(asyncio.sleep(100)), None)  # still running
    clock["t"] = 100.0
    await mgr.gc()
    assert mgr.get("t1") is rs, "a still-running run must never be GC'd"
    rs.task.cancel()
