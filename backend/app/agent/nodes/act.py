from __future__ import annotations

import json

from langchain_core.messages import AIMessage

from app.agent.state import AgentState
from app.browser.base import BrowserSession
from app.events.emitter import EventEmitter
from app.telemetry.records import StepRecord
from app.telemetry.store import TrajectoryStore
from app.tools.dispatcher import ToolDispatcher

# Actions that are legitimately repeated (reading, scrolling, waiting) — excluded from loop detection.
_REPEATABLE_ACTIONS = {"scroll", "wait_for", "extract", "search_page", "find_elements",
                       "observe_tab", "switch_tab"}
_ACTION_WINDOW = 10


def _action_sig(action, page_url: str = "", target: str = "") -> str | None:
    """A signature identifying a committing action + its target ON a given page, or None for
    repeatable actions. Two calls collide (=loop) only when the same action hits the same target
    with the same args on the SAME page — so a repeated click that navigates to a new page each
    time (e.g. picking the always-index autocomplete result) is progress, not a loop.

    `target` is the acted-on element's "role:name" identity: pages that renumber [N] every turn
    (MakeMyTrip) would otherwise make every re-click of the same button look like a new action."""
    if action is None or action.name in _REPEATABLE_ACTIONS:
        return None
    args = dict(action.args)
    if target and "index" in args:
        args["index"] = target
    return f"{page_url}|{action.name}:{json.dumps(args, sort_keys=True)[:160]}"


def _target_identity(action, observation) -> str:
    """The acted-on element's "role:name" from the observation the action was decided against."""
    idx = action.args.get("index") if action is not None else None
    if idx is None or observation is None:
        return ""
    for el in observation.elements:
        if el.index == idx:
            return f"{el.role}:{el.name}"
    return ""


def build_act_node(
    dispatcher: ToolDispatcher,
    session: BrowserSession,
    emitter: EventEmitter,
    store: TrajectoryStore,
    mem_store=None,
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
            if mem_store is not None:
                for k, v in memory.items():
                    if state.agent_memory.get(k) != v:
                        mem_store.append(state.thread_id, k, v)

        # The page the action was performed on — same action on a new page each turn is progress,
        # not a loop (state.observation is the pre-action page the tool call was decided against).
        page_url = state.observation.url if state.observation else ""
        sig = _action_sig(merged.get("last_action"), page_url,
                          _target_identity(merged.get("last_action"), state.observation))
        if sig is not None:
            merged["recent_actions"] = (state.recent_actions + [sig])[-_ACTION_WINDOW:]

        record = StepRecord(
            step=state.step,
            node="act",
            action=merged.get("last_action"),
            result=merged.get("last_result"),
        )
        await store.save(state.thread_id, record)
        return {"messages": tool_messages, "history": [record], **merged}

    return act
