from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from app.events.protocol import AgentEvent


@runtime_checkable
class EventSink(Protocol):
    async def emit(self, event: "AgentEvent") -> None: ...


class BufferSink:
    """Dev/test EventSink — collects events in a list."""

    def __init__(self) -> None:
        self.events: list = []

    async def emit(self, event) -> None:
        self.events.append(event)
