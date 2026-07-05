"""Wrap a BrowserSession to capture the SoM screenshot after each observe — the judge needs the
trajectory's screenshots. Satisfies the same BrowserSession port (Liskov), so it drops into the graph
unchanged and adds nothing to the agent's own view."""
from __future__ import annotations

import base64


class RecordingSession:
    def __init__(self, inner) -> None:
        self._inner = inner
        self.shots: list[str] = []
        self.on_frame = None

    async def start(self) -> None:
        await self._inner.start()

    async def stop(self) -> None:
        await self._inner.stop()

    async def observe(self, **kw):
        obs = await self._inner.observe(**kw)
        shot = getattr(self._inner, "latest_screenshot", None)
        if shot:
            self.shots.append(base64.b64encode(shot).decode())
        return obs

    async def act(self, call):
        return await self._inner.act(call)

    async def navigate(self, url: str):
        return await self._inner.navigate(url)

    async def tabs(self):
        return await self._inner.tabs()

    @property
    def latest_screenshot(self):
        return getattr(self._inner, "latest_screenshot", None)
