"""Run survival across cockpit reconnect (spec §5, Milestone 1b).

The agent run is owned by a `RunSession` in the process-level `RunManager`, NOT by the cockpit
WebSocket. A cockpit refresh detaches the *view* (the `FanoutSink`'s current socket) but leaves the
run — and its browser — untouched. On reconnect the cockpit replays buffered events and resumes live.

Nothing here knows about FastAPI: a "sink" is just an async callable that takes a JSON-able dict, so
the whole module is unit-testable with a plain recorder (see tests/api/test_run_manager.py)."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Awaitable, Callable, Optional

from app.events.protocol import AgentEvent

Send = Callable[[dict], Awaitable[None]]


class FanoutSink:
    """An `EventSink` that buffers every event (bounded) and, while a socket is attached, forwards
    each event to it. Re-attachable: a reconnecting cockpit gets the full buffered history replayed
    (in order) before it starts receiving live events.

    All buffer/send access is serialized under one lock so a reconnect's replay can never interleave
    with a live emit (which would reorder or duplicate frames)."""

    def __init__(self, buffer_size: int = 1000) -> None:
        self._buffer: deque[AgentEvent] = deque(maxlen=buffer_size)
        self._send: Optional[Send] = None
        self._lock = asyncio.Lock()

    @property
    def attached(self) -> bool:
        return self._send is not None

    async def emit(self, event: AgentEvent) -> None:
        async with self._lock:
            self._buffer.append(event)
            if self._send is not None:
                try:
                    await self._send(event.model_dump())
                except Exception:
                    pass  # socket died mid-send; detach() lands on disconnect

    async def attach(self, send: Send) -> None:
        """Replay the buffered history to `send`, then make it the live target. Held under the lock
        so no live emit slips in between the replay and going live."""
        async with self._lock:
            for event in list(self._buffer):
                await send(event.model_dump())
            self._send = send

    async def detach(self, send: Optional[Send] = None) -> None:
        """Stop forwarding. If `send` is given, only detach when it is still the current target —
        a stale detach (the old socket closing after a newer one already attached) is a no-op."""
        async with self._lock:
            if send is None or self._send is send:
                self._send = None


class RunSession:
    """One agent run: owns the `run_task`, the browser `cleanup`, the re-attachable `FanoutSink`,
    and the answer queue that feeds AskUser interrupts."""

    def __init__(self, thread_id: str) -> None:
        self.thread_id = thread_id
        self.sink = FanoutSink()
        self.task: Optional[asyncio.Task] = None
        self.done: bool = False
        self.result: Optional[dict] = None
        self.finished_at: Optional[float] = None
        self._cleanup: Optional[Callable[[], Awaitable[None]]] = None
        self._cleaned = False
        self._answers: asyncio.Queue[str] = asyncio.Queue()

    def bind(self, task: asyncio.Task, cleanup: Optional[Callable[[], Awaitable[None]]]) -> None:
        self.task = task
        self._cleanup = cleanup

    async def attach(self, send: Send) -> None:
        await self.sink.attach(send)

    async def detach(self, send: Optional[Send] = None) -> None:
        await self.sink.detach(send)

    async def answer(self, text: str) -> None:
        self._answers.put_nowait(text)

    async def answer_provider(self, question: dict) -> str:
        return await self._answers.get()

    async def stop(self) -> None:
        """Cancel the run task (if still going) and run cleanup exactly once."""
        if self.task is not None and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except BaseException:
                pass
        if self._cleanup is not None and not self._cleaned:
            self._cleaned = True
            try:
                await self._cleanup()
            except Exception:
                pass


class RunManager:
    """Process-level registry of live runs, keyed by `thread_id`. Also GCs runs that have finished
    and lost their viewer, so an abandoned run cannot leak a browser forever."""

    def __init__(self, *, ttl_seconds: float = 120.0, time_fn: Callable[[], float] = time.monotonic) -> None:
        self._runs: dict[str, RunSession] = {}
        self._ttl = ttl_seconds
        self._now = time_fn

    def get(self, thread_id: str) -> Optional[RunSession]:
        return self._runs.get(thread_id)

    async def create(self, thread_id: str) -> RunSession:
        """Register a fresh run for `thread_id`, tearing down any prior run under the same id."""
        old = self._runs.get(thread_id)
        if old is not None:
            await old.stop()
        rs = RunSession(thread_id)
        self._runs[thread_id] = rs
        return rs

    def mark_done(self, thread_id: str, result: dict) -> None:
        rs = self._runs.get(thread_id)
        if rs is not None:
            rs.done = True
            rs.result = result
            rs.finished_at = self._now()

    async def remove(self, thread_id: str) -> None:
        rs = self._runs.pop(thread_id, None)
        if rs is not None:
            await rs.stop()

    async def gc(self) -> None:
        """Collect runs that are terminal AND unattached AND past the reconnect TTL."""
        now = self._now()
        for thread_id, rs in list(self._runs.items()):
            if (
                rs.done
                and not rs.sink.attached
                and rs.finished_at is not None
                and (now - rs.finished_at) > self._ttl
            ):
                await self.remove(thread_id)
