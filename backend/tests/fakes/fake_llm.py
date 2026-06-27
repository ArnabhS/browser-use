from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage
from pydantic import BaseModel
from typing import Sequence


def ai(content: str, tool_calls: list[dict] | None = None) -> AIMessage:
    return AIMessage(content=content, tool_calls=tool_calls or [])


class FakeLLMClient:
    """Pops scripted AIMessages in order; raises IndexError when exhausted."""

    def __init__(self, turns: list[AIMessage]) -> None:
        self._turns = list(turns)
        self.calls = 0

    async def complete(self, *, messages: list[BaseMessage], tools: Sequence[type[BaseModel]]) -> AIMessage:
        self.calls += 1
        return self._turns.pop(0)
