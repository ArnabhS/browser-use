from __future__ import annotations

from typing import Protocol, runtime_checkable

from browser_agent_contracts import ActionCall, ActionResult, Observation

from app.telemetry.records import TabInfo


@runtime_checkable
class BrowserSession(Protocol):
    async def observe(self, *, include_som: bool = True) -> Observation: ...
    async def act(self, call: ActionCall) -> ActionResult: ...
    async def navigate(self, url: str) -> ActionResult: ...
    async def tabs(self) -> list[TabInfo]: ...
