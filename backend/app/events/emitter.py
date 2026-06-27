from __future__ import annotations

from typing import Any

from app.events.protocol import (
    AgentEvent,
    ERROR,
    FINALIZE,
    MEMORY_UPDATE,
    OBSERVATION,
    PLAN_UPDATE,
    REASONING,
    STATUS,
    TOOL_CALL,
)
from app.events.sink import EventSink


class EventEmitter:
    """Builds typed AgentEvents and forwards them to the injected sink."""

    def __init__(self, sink: EventSink) -> None:
        self._sink = sink

    async def _emit(self, type_: str, data: dict[str, Any]) -> None:
        await self._sink.emit(AgentEvent(type=type_, data=data))

    async def emit_status(self, phase: str, message: str) -> None:
        await self._emit(STATUS, {"phase": phase, "message": message})

    async def emit_reasoning(self, text: str) -> None:
        await self._emit(REASONING, {"text": text})

    async def emit_tool_call(self, name: str, args: dict[str, Any]) -> None:
        await self._emit(TOOL_CALL, {"name": name, "args": args})

    async def emit_observation(self, url: str, n_elements: int) -> None:
        await self._emit(OBSERVATION, {"url": url, "elements": n_elements})

    async def emit_plan(self, steps: list[str]) -> None:
        await self._emit(PLAN_UPDATE, {"steps": steps})

    async def emit_memory(self, key: str) -> None:
        await self._emit(MEMORY_UPDATE, {"key": key})

    async def emit_error(self, message: str) -> None:
        await self._emit(ERROR, {"message": message})

    async def emit_finalize(self, success: bool, reason: str) -> None:
        await self._emit(FINALIZE, {"success": success, "reason": reason})
