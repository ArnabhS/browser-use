from __future__ import annotations

import operator
from typing import Annotated, Literal

from browser_agent_contracts import ActionCall, ActionResult, Observation
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field

from app.telemetry.records import ErrorCode, StepRecord


class AgentState(BaseModel):
    """Single source of truth flowing through the agent graph."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    task: str
    thread_id: str

    messages: Annotated[list[BaseMessage], add_messages] = Field(default_factory=list)
    observation: Observation | None = None
    agent_memory: dict[str, str] = Field(default_factory=dict)
    history: Annotated[list[StepRecord], operator.add] = Field(default_factory=list)

    last_action: ActionCall | None = None
    last_result: ActionResult | None = None

    status: Literal["running", "done", "failed"] = "running"
    error_code: ErrorCode | None = None
    step: int = 0
    nudge_count: int = 0
    stuck_count: int = 0
    # Rolling window of recent NON-repeatable action signatures — for action-repetition loop
    # detection (catches clear/retype-style loops that the page-signature stuck_count misses because
    # the page superficially changes). Replaced each act step; see act/reason nodes.
    recent_actions: list[str] = Field(default_factory=list)
    finished: bool = False
    success: bool | None = None
    reason: str = ""
