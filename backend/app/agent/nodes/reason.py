from __future__ import annotations

import re

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.compaction import compact_for_llm
from app.agent.prompt import build_memory_message, build_system_message
from app.agent.state import AgentState
from app.events.emitter import EventEmitter
from app.llm.base import LLMClient
from app.telemetry.records import ErrorCode, StepRecord
from app.tools.specs import TOOL_SPECS

_REMINDER = (
    "Before acting you must explain your reasoning in plain text. "
    "Describe the next step, THEN call one tool."
)
# Matches a leading "Assessment: <text>" line (tolerating markdown bullets/bold/heading marks).
_ASSESS_RE = re.compile(r"^[\s*_#>\-]*assessment\b\s*[:\-–]\s*(.+)$", re.IGNORECASE)


def _text(msg: AIMessage) -> str:
    return msg.content if isinstance(msg.content, str) else " ".join(
        b.get("text", "") for b in msg.content if isinstance(b, dict)
    )


def _has_reasoning(msg: AIMessage) -> bool:
    return len(_text(msg).strip()) >= 3


def _assessment_line(msg: AIMessage) -> str | None:
    """The text of a leading `Assessment:` line, if the reasoning opens with one."""
    for line in _text(msg).splitlines()[:3]:
        m = _ASSESS_RE.match(line.strip())
        if m and m.group(1).strip():
            return m.group(1).strip()[:300]
    return None


def _usage(msg: AIMessage) -> tuple[int, int]:
    u = getattr(msg, "usage_metadata", None) or {}
    return int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0))


def build_reason_node(llm: LLMClient, emitter: EventEmitter):
    async def reason(state: AgentState) -> dict:
        messages = list(state.messages)
        nudge_delta: dict = {}

        # Hard stop: the page has not changed for many turns — actions are having no effect.
        if state.stuck_count >= 8:
            await emitter.emit_error("stuck: repeated actions had no effect on the page")
            return {
                "status": "failed",
                "error_code": ErrorCode.STUCK,
                "finished": True,
                "reason": "Stuck — the same actions kept having no effect on the page.",
            }

        # Action-repetition loop guard: catches loops the page-signature stuck_count misses — the
        # agent keeps firing the SAME committing action (clear/retype, re-clicking a dead button)
        # while the page superficially changes. Break at 5 repeats; nudge hard at 3.
        recent = state.recent_actions
        loop_repeats = recent.count(recent[-1]) if recent else 0
        if loop_repeats >= 5:
            await emitter.emit_error("stuck: the same action was repeated with no progress")
            return {
                "status": "failed",
                "error_code": ErrorCode.STUCK,
                "finished": True,
                "reason": "Stuck — the same action was repeated over and over without making progress.",
            }
        if loop_repeats >= 3:
            messages.append(HumanMessage(content=(
                f"You have used the SAME action {loop_repeats} times and it is NOT making progress. Do "
                "NOT repeat it. If you already entered the text, SUBMIT it (PressKey 'Enter' or click the "
                "submit/search button) instead of re-typing. Otherwise pick a DIFFERENT element, scroll "
                "to find what you need, or Complete(success=false) if you are genuinely blocked."
            )))
            nudge_delta = {"nudge_count": state.nudge_count + 1}

        # Re-entry nudge: last turn produced no tool call.
        last = messages[-1] if messages else None
        if isinstance(last, AIMessage) and not last.tool_calls:
            messages.append(HumanMessage(content="You did not call any tool. Call a tool or Complete()."))
            nudge_delta = {"nudge_count": state.nudge_count + 1}

        # Stuck nudge: the page is unchanged — the recent action(s) had no effect. Break the loop.
        if state.stuck_count >= 2:
            messages.append(HumanMessage(content=(
                f"The page has NOT changed after your last {state.stuck_count} action(s) — they had no "
                "effect. Do NOT repeat the same action. Instead: Scroll to reveal off-screen content, "
                "WaitFor(2) if it may still be loading, or pick a DIFFERENT element. If you genuinely "
                "cannot proceed, call Complete(success=false)."
            )))
            nudge_delta = {"nudge_count": state.nudge_count + 1}

        compacted, ctx_status = compact_for_llm(messages)
        if compacted and isinstance(compacted[0], AIMessage):
            compacted = [HumanMessage(content=state.task), *compacted]
        system = build_system_message(state)
        # Working memory rides OUTSIDE the cache-marked system block (see build_memory_message) —
        # right after it, before the conversation, so the cached prefix stays byte-stable.
        mem = build_memory_message(state)
        prefix = [system, mem] if mem is not None else [system]
        ai = await llm.complete(messages=[*prefix, *compacted], tools=TOOL_SPECS)

        in_tok, out_tok = _usage(ai)
        ctx_status["input_tokens"] = in_tok
        await emitter.emit_context_status(ctx_status)

        # Think-before-act enforcement: retry once if a tool call lacks reasoning.
        if ai.tool_calls and not _has_reasoning(ai):
            retry_msgs = [*prefix, *compacted, ai, HumanMessage(content=_REMINDER)]
            ai = await llm.complete(messages=retry_msgs, tools=TOOL_SPECS)
            if ai.tool_calls and not _has_reasoning(ai):
                await emitter.emit_error("Reasoning missing after retry")
                return {
                    "messages": [ai],
                    "status": "failed",
                    "error_code": ErrorCode.REASONING_MISSING,
                    "finished": True,
                    **nudge_delta,
                }

        # P0-3: the prompt asks the model to OPEN with an `Assessment:` of its last action. When it
        # does, surface it as a distinct cockpit signal. Deliberately NOT enforced via a retry — a
        # full LLM re-call to nudge a formatting label would double cost; the prompt + the emitted
        # signal deliver the grounding value, and stuck-detection already catches no-effect actions.
        assessment = _assessment_line(ai)
        if assessment:
            await emitter.emit_evaluation(assessment)
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
