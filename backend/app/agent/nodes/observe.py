from __future__ import annotations

from langchain_core.messages import HumanMessage

from app.agent.format import format_observation
from app.agent.state import AgentState
from app.browser.base import BrowserSession
from app.events.emitter import EventEmitter
from app.telemetry.records import StepRecord


def build_observe_node(session: BrowserSession, emitter: EventEmitter):
    async def observe(state: AgentState) -> dict:
        obs = await session.observe()
        await emitter.emit_observation(obs.url, len(obs.elements))
        return {
            "observation": obs,
            "messages": [HumanMessage(content=format_observation(obs))],
            "history": [StepRecord(step=state.step, node="observe")],
        }

    return observe
