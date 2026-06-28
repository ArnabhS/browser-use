from __future__ import annotations

import base64

from langchain_core.messages import HumanMessage

from app.agent.format import format_observation
from app.agent.state import AgentState
from app.browser.base import BrowserSession
from app.events.emitter import EventEmitter
from app.telemetry.records import StepRecord


def build_observe_node(session: BrowserSession, emitter: EventEmitter, *, use_vision: bool = False):
    async def observe(state: AgentState) -> dict:
        obs = await session.observe()
        await emitter.emit_observation(obs.url, len(obs.elements))
        text = format_observation(obs)
        shot = getattr(session, "latest_screenshot", None)
        if use_vision and shot:
            b64 = base64.b64encode(shot).decode()
            content = [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]
        else:
            content = text
        return {
            "observation": obs,
            "messages": [HumanMessage(content=content, name="observation")],
            "history": [StepRecord(step=state.step, node="observe")],
        }

    return observe
