from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Protocol

logger = logging.getLogger(__name__)

# Push a base64-jpeg frame + a small metadata dict (url, w, h) outward (e.g. to the WebSocket).
OnFrame = Callable[[str, dict], Awaitable[None]]


class CDPSession(Protocol):
    """The slice of a Playwright CDP session the streamer needs (kept narrow for fakes/tests)."""

    def on(self, event: str, handler: Callable[[dict], None]) -> None: ...
    async def send(self, method: str, params: dict | None = None) -> dict: ...


class ScreencastStreamer:
    """Pumps CDP `Page.screencastFrame`s from ONE cdp session out through `on_frame`.

    CDP screencast is ack-gated: Chrome sends the next frame only after we ack the last, so
    acking *after* we forward the frame throttles the stream to however fast the consumer (the
    WebSocket) drains — no unbounded buffering. Entirely best-effort: any CDP failure is logged
    and swallowed, so a broken stream never takes the agent run down with it.
    """

    def __init__(
        self, *, quality: int = 50, max_width: int = 960, max_height: int = 640, every_nth: int = 2
    ) -> None:
        self._quality = quality
        self._max_width = max_width
        self._max_height = max_height
        self._every_nth = every_nth
        self._cdp: CDPSession | None = None
        self._on_frame: OnFrame | None = None
        self._url_getter: Callable[[], str] = lambda: ""
        self._handler: Callable[[dict], None] | None = None
        self._queue: asyncio.Queue[tuple[str, int]] | None = None
        self._task: asyncio.Task | None = None

    async def start(self, cdp: CDPSession, *, on_frame: OnFrame, url_getter: Callable[[], str]) -> None:
        """Begin (or re-point to) a screencast on `cdp`. Stops any existing one first."""
        await self.stop()
        self._cdp = cdp
        self._on_frame = on_frame
        self._url_getter = url_getter
        self._queue = asyncio.Queue(maxsize=4)
        self._handler = self._make_handler(self._queue)
        cdp.on("Page.screencastFrame", self._handler)
        try:
            await cdp.send("Page.enable")
        except Exception:
            pass  # some targets don't need/allow it — startScreencast still works
        try:
            await cdp.send(
                "Page.startScreencast",
                {
                    "format": "jpeg",
                    "quality": self._quality,
                    "maxWidth": self._max_width,
                    "maxHeight": self._max_height,
                    "everyNthFrame": self._every_nth,
                },
            )
        except Exception as exc:
            logger.warning("screencast start failed (streaming disabled): %s", exc)
            await self.stop()
            return
        self._task = asyncio.create_task(self._consume())

    def _make_handler(self, queue: asyncio.Queue) -> Callable[[dict], None]:
        def handler(params: dict) -> None:
            # Sync CDP callback: hand off to the async consumer. If the consumer is behind
            # (queue full), drop this frame — the next one carries the newer page state anyway.
            try:
                queue.put_nowait((params.get("data", ""), params.get("sessionId", 0)))
            except asyncio.QueueFull:
                pass

        return handler

    async def _consume(self) -> None:
        assert self._queue is not None
        while True:
            data, session_id = await self._queue.get()
            if self._on_frame is not None and data:
                try:
                    await self._on_frame(data, {"url": self._url_getter()})
                except Exception:
                    pass  # a dead socket must not kill the stream loop
            # Ack even on forward failure, so Chrome keeps the frames coming.
            try:
                await self._cdp.send("Page.screencastFrameAck", {"sessionId": session_id})  # type: ignore[union-attr]
            except Exception:
                pass

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except BaseException:
                pass
            self._task = None
        cdp = self._cdp
        if cdp is not None:
            try:
                await cdp.send("Page.stopScreencast")
            except Exception:
                pass
            remover = getattr(cdp, "remove_listener", None)
            if remover is not None and self._handler is not None:
                try:
                    remover("Page.screencastFrame", self._handler)
                except Exception:
                    pass
            detach = getattr(cdp, "detach", None)
            if detach is not None:
                try:
                    await detach()
                except Exception:
                    pass
        self._cdp = None
        self._handler = None
        self._queue = None
