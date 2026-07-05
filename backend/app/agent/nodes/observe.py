from __future__ import annotations

import base64

from langchain_core.messages import HumanMessage

from app.agent.format import format_observation
from app.agent.state import AgentState
from app.browser.base import BrowserSession
from app.events.emitter import EventEmitter
from app.telemetry.records import StepRecord


def _signature(obs) -> tuple:
    """Coarse page fingerprint — same url + same element set => the page did not change."""
    return (obs.url, tuple((e.role, e.name) for e in obs.elements))


def _stamp_new(obs, prev):
    """Mark elements absent from the previous (same-page) observation as `is_new` — they appeared as
    a result of the agent's last action. On a fresh page or the first turn, nothing is new."""
    if prev is None or prev.url != obs.url:
        return obs
    prev_sigs = {(e.role, e.name, e.value) for e in prev.elements}
    elements = [e.model_copy(update={"is_new": (e.role, e.name, e.value) not in prev_sigs})
                for e in obs.elements]
    return obs.model_copy(update={"elements": elements})


def build_observe_node(session: BrowserSession, emitter: EventEmitter, *, use_vision: bool = False):
    async def observe(state: AgentState) -> dict:
        obs = await session.observe()
        obs = _stamp_new(obs, state.observation)
        await emitter.emit_observation(obs.url, len(obs.elements))
        # If the page is identical to last turn, the previous action had no effect — track a
        # "stuck" counter so the reason node can break a repeat-loop (clicking a dead element).
        prev = state.observation
        unchanged = prev is not None and _signature(obs) == _signature(prev)
        stuck = state.stuck_count + 1 if unchanged else 0
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
            "stuck_count": stuck,
        }

    return observe
