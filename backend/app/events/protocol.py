from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

STATUS = "status"
REASONING = "reasoning"
TOOL_CALL = "tool_call"
OBSERVATION = "observation"
USAGE = "usage"
PLAN_UPDATE = "plan_update"
MEMORY_UPDATE = "memory_update"
ERROR = "error"
FINALIZE = "finalize"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentEvent(BaseModel):
    event: str
    data: dict[str, Any] = Field(default_factory=dict)
    ts: str = Field(default_factory=_now_iso)
