from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.prompt import build_system_message
from app.agent.state import AgentState
from app.events.emitter import EventEmitter
from app.llm.base import LLMClient
from app.telemetry.records import ErrorCode, StepRecord
from app.tools.specs import TOOL_SPECS

_REMINDER = (
    "Before acting you must explain your reasoning in plain text. "
    "Describe the next step, THEN call one tool."
)


def _text(msg: AIMessage) -> str:
    return msg.content if isinstance(msg.content, str) else " ".join(
        b.get("text", "") for b in msg.content if isinstance(b, dict)
    )


def _has_reasoning(msg: AIMessage) -> bool:
    return len(_text(msg).strip()) >= 3


def _usage(msg: AIMessage) -> tuple[int, int]:
    u = getattr(msg, "usage_metadata", None) or {}
    return int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0))


def build_reason_node(llm: LLMClient, emitter: EventEmitter):
    async def reason(state: AgentState) -> dict:
        messages = list(state.messages)
        nudge_delta: dict = {}

        # Re-entry nudge: last turn produced no tool call.
        last = messages[-1] if messages else None
        if isinstance(last, AIMessage) and not last.tool_calls:
            messages.append(HumanMessage(content="You did not call any tool. Call a tool or Complete()."))
            nudge_delta = {"nudge_count": state.nudge_count + 1}

        system = build_system_message(state)
        ai = await llm.complete(messages=[system, *messages], tools=TOOL_SPECS)

        # Think-before-act enforcement: retry once if a tool call lacks reasoning.
        if ai.tool_calls and not _has_reasoning(ai):
            retry_msgs = [system, *messages, ai, HumanMessage(content=_REMINDER)]
            ai = await llm.complete(messages=retry_msgs, tools=TOOL_SPECS)
            if ai.tool_calls and not _has_reasoning(ai):
                await emitter.emit_error("Reasoning missing after retry")
                return {
                    "messages": [ai],
                    "status": "failed",
                    "error_code": ErrorCode.REASONING_MISSING,
                    "finished": True,
                }

        if _has_reasoning(ai):
            await emitter.emit_reasoning(_text(ai).strip())
        in_tok, out_tok = _usage(ai)
        return {
            "messages": [ai],
            "step": state.step + 1,
            "history": [StepRecord(step=state.step + 1, node="reason", input_tokens=in_tok, output_tokens=out_tok)],
            **nudge_delta,
        }

    return reason
