from __future__ import annotations

from langchain_core.messages import AIMessage

from app.agent.state import AgentState

_DEFAULT_MAX_STEPS = 25


def route_after_reason(state: AgentState, max_steps: int = _DEFAULT_MAX_STEPS) -> str:
    if state.finished or state.status == "failed":
        return "finalize"
    if state.step >= max_steps:
        return "finalize"
    last = state.messages[-1] if state.messages else None
    if isinstance(last, AIMessage) and last.tool_calls:
        return "act"
    # no tool call: nudge once, then give up
    if state.nudge_count < 1:
        return "reason"
    return "finalize"


def route_after_act(state: AgentState) -> str:
    return "finalize" if state.finished else "observe"
