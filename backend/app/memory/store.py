# backend/app/memory/store.py
"""MemoryStore port + AsyncMarkdownMemory: non-blocking enqueue, background aiofiles writer."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Protocol

import aiofiles

from app.memory.document import append_run, build_document, parse_knowledge, update_knowledge

logger = logging.getLogger(__name__)


class MemoryStore(Protocol):
    async def start(self) -> None: ...
    async def stop(self, timeout: float = 2.0) -> None: ...
    def append(self, thread_id: str, key: str, value: str) -> None: ...
    def append_run(self, thread_id: str, summary: str) -> None: ...
    async def load(self, thread_id: str) -> dict[str, str]: ...


class AsyncMarkdownMemory:
    """Writes runs/{thread_id}/memory.md off the hot path via an asyncio.Queue + worker."""

    def __init__(self, base_dir: str = "runs", max_queue: int = 1000) -> None:
        self._base = Path(base_dir)
        self._queue: asyncio.Queue[tuple[str, str, str, str]] = asyncio.Queue(maxsize=max_queue)
        self._worker: asyncio.Task | None = None

    def _path(self, thread_id: str) -> Path:
        return self._base / thread_id / "memory.md"

    # --- non-blocking producers (sync signatures; enqueue only) ---
    def append(self, thread_id: str, key: str, value: str) -> None:
        self._enqueue(("knowledge", thread_id, key, value))

    def append_run(self, thread_id: str, summary: str) -> None:
        self._enqueue(("run", thread_id, summary, ""))

    def _enqueue(self, item: tuple[str, str, str, str]) -> None:
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            logger.warning("memory queue full — dropping write %s/%s", item[0], item[1])

    # --- lifecycle ---
    async def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._run())

    async def stop(self, timeout: float = 2.0) -> None:
        if self._worker is None:
            return
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("memory queue did not drain within %.1fs", timeout)
        self._worker.cancel()
        try:
            await self._worker
        except asyncio.CancelledError:
            pass
        self._worker = None

    # --- worker ---
    async def _run(self) -> None:
        while True:
            kind, thread_id, a, b = await self._queue.get()
            try:
                await self._apply(kind, thread_id, a, b)
            except Exception:  # never let one bad write kill the worker
                logger.exception("memory write failed for %s", thread_id)
            finally:
                self._queue.task_done()

    async def _apply(self, kind: str, thread_id: str, a: str, b: str) -> None:
        path = self._path(thread_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        md = path.read_text() if path.exists() else build_document({}, [])
        md = update_knowledge(md, a, b) if kind == "knowledge" else append_run(md, a)
        async with aiofiles.open(path, "w") as f:
            await f.write(md)

    async def load(self, thread_id: str) -> dict[str, str]:
        path = self._path(thread_id)
        if not path.exists():
            return {}
        async with aiofiles.open(path, "r") as f:
            return parse_knowledge(await f.read())
