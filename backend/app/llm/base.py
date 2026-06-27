from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from langchain_core.messages import AIMessage, BaseMessage
from pydantic import BaseModel


@runtime_checkable
class LLMClient(Protocol):
    """Returns the model's next turn as an AIMessage (content = reasoning, tool_calls = actions)."""

    async def complete(
        self, *, messages: list[BaseMessage], tools: Sequence[type[BaseModel]]
    ) -> AIMessage: ...
