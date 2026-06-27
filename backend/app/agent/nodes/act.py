from __future__ import annotations

from langchain_core.messages import AIMessage

from app.agent.state import AgentState
from app.browser.base import BrowserSession
from app.events.emitter import EventEmitter
from app.telemetry.records import StepRecord
from app.telemetry.store import TrajectoryStore
from app.tools.dispatcher import ToolDispatcher


def build_act_node(
    dispatcher: ToolDispatcher,
    session: BrowserSession,
    emitter: EventEmitter,
    store: TrajectoryStore,
):
    async def act(state: AgentState) -> dict:
        last = state.messages[-1]
        tool_calls = last.tool_calls if isinstance(last, AIMessage) else []

        tool_messages = []
        merged: dict = {}
        memory = dict(state.agent_memory)
        for tc in tool_calls:
            msg, delta = await dispatcher.dispatch(tc, state=state, session=session, emitter=emitter)
            tool_messages.append(msg)
            if "agent_memory" in delta:
                memory.update(delta.pop("agent_memory"))
            merged.update(delta)
        if memory != state.agent_memory:
            merged["agent_memory"] = memory

        record = StepRecord(
            step=state.step,
            node="act",
            action=merged.get("last_action"),
            result=merged.get("last_result"),
        )
        await store.save(state.thread_id, record)
        return {"messages": tool_messages, "history": [record], **merged}

    return act
