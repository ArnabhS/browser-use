from __future__ import annotations

from browser_agent_contracts import ActionCall, ActionResult, Observation, Viewport


def _blank() -> Observation:
    return Observation(url="about:blank", title="", viewport=Viewport(width=1280, height=800))


class FakeBrowserSession:
    """Scripted BrowserSession for graph tests. Records every act()."""

    def __init__(self, observations: list[Observation] | None = None,
                 results: list[ActionResult] | None = None) -> None:
        self._obs = list(observations or [])
        self._results = list(results or [])
        self.acts: list[ActionCall] = []

    async def observe(self, *, include_som: bool = True) -> Observation:
        return self._obs.pop(0) if self._obs else _blank()

    async def act(self, call: ActionCall) -> ActionResult:
        self.acts.append(call)
        return self._results.pop(0) if self._results else ActionResult(success=True, reason="ok")

    async def navigate(self, url: str) -> ActionResult:
        return await self.act(ActionCall(name="navigate", args={"url": url}))

    async def tabs(self):
        return []
