from __future__ import annotations

from enum import Enum

from browser_agent_contracts import ActionCall, ActionResult
from pydantic import BaseModel


class ErrorCode(str, Enum):
    ACTION_TIMEOUT = "ACTION_TIMEOUT"
    REASONING_MISSING = "REASONING_MISSING"
    NO_ACTION = "NO_ACTION"
    MAX_STEPS = "MAX_STEPS"
    STUCK = "STUCK"


class StepRecord(BaseModel):
    step: int
    node: str
    action: ActionCall | None = None
    result: ActionResult | None = None
    error_code: ErrorCode | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    model: str = ""


class TabInfo(BaseModel):
    target_id: str
    url: str
    title: str = ""
    active: bool = False
