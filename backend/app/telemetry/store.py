from __future__ import annotations

from typing import Protocol, runtime_checkable

from .records import StepRecord


@runtime_checkable
class TrajectoryStore(Protocol):
    async def save(self, thread_id: str, record: StepRecord) -> None: ...


class InMemoryTrajectoryStore:
    """Dev/test TrajectoryStore — keeps records per thread in RAM."""

    def __init__(self) -> None:
        self.records: dict[str, list[StepRecord]] = {}

    async def save(self, thread_id: str, record: StepRecord) -> None:
        self.records.setdefault(thread_id, []).append(record)
