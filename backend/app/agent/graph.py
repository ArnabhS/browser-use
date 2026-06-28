from __future__ import annotations

from browser_agent_contracts.models import ActionCall, ActionResult, Observation
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from app.agent.nodes.act import build_act_node
from app.agent.nodes.observe import build_observe_node
from app.agent.nodes.reason import build_reason_node
from app.agent.routing import route_after_act, route_after_reason
from app.agent.state import AgentState
from app.browser.base import BrowserSession
from app.events.emitter import EventEmitter
from app.llm.base import LLMClient
from app.telemetry.records import ErrorCode, StepRecord
from app.telemetry.store import TrajectoryStore
from app.tools.dispatcher import ToolDispatcher

# Types stored in checkpoint state that are not in langgraph's built-in safe list.
# Passing class objects lets _normalize_module_keys extract (module, classname) tuples
# automatically, which is what _check_allowed() compares against.
_ALLOWED_MSGPACK_MODULES = [Observation, ActionCall, ActionResult, StepRecord]


def _checkpointer() -> InMemorySaver:
    return InMemorySaver(
        serde=JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_MSGPACK_MODULES)
    )


def build_finalize_node(emitter: EventEmitter, max_steps: int):
    """Resolve terminal status/error in one place and emit the finalize event.

    A closure (not functools.partial): LangGraph may mis-detect a partial of a
    coroutine as a sync node and fail to await it.
    """

    async def finalize(state: AgentState) -> dict:
        if state.finished and state.status != "failed":
            delta = {"status": "done" if state.success else "failed", "success": state.success}
        elif state.status == "failed":
            delta = {}  # reason node already set status/error_code
        elif state.step >= max_steps:
            delta = {"status": "failed", "error_code": ErrorCode.MAX_STEPS}
        else:
            delta = {"status": "failed", "error_code": ErrorCode.NO_ACTION}
        err = delta.get("error_code") or state.error_code
        reason = state.reason or (err.value if err else "")
        await emitter.emit_finalize(bool(state.success), reason)
        return {**delta, "history": [StepRecord(step=state.step, node="finalize",
                                                error_code=delta.get("error_code"))]}

    return finalize


def build_graph(*, session: BrowserSession, llm: LLMClient, emitter: EventEmitter,
                store: TrajectoryStore, max_steps: int = 25, use_vision: bool = False):
    g = StateGraph(AgentState)
    g.add_node("observe", build_observe_node(session, emitter, use_vision=use_vision))
    g.add_node("reason", build_reason_node(llm, emitter))
    g.add_node("act", build_act_node(ToolDispatcher(), session, emitter, store))
    g.add_node("finalize", build_finalize_node(emitter, max_steps))

    g.add_edge(START, "observe")
    g.add_edge("observe", "reason")
    g.add_conditional_edges("reason", lambda s: route_after_reason(s, max_steps),
                            {"act": "act", "reason": "reason", "finalize": "finalize"})
    g.add_conditional_edges("act", route_after_act, {"observe": "observe", "finalize": "finalize"})
    g.add_edge("finalize", END)
    return g.compile(checkpointer=_checkpointer())
