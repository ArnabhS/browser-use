from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

STATUS = "status"
REASONING = "reasoning"
EVALUATION = "evaluation"  # the model's self-assessment of its previous action (P0-3)
TOOL_CALL = "tool_call"
OBSERVATION = "observation"
USAGE = "usage"
PLAN_UPDATE = "plan_update"
MEMORY_UPDATE = "memory_update"
ERROR = "error"
FINALIZE = "finalize"
STREAM = "stream"  # incremental LLM token
QUESTION = "question"
CONTEXT_STATUS = "context_status"
FRAME = "frame"  # a live browser screencast frame (base64 jpeg)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentEvent(BaseModel):
    event: str
    data: dict[str, Any] = Field(default_factory=dict)
    ts: str = Field(default_factory=_now_iso)
