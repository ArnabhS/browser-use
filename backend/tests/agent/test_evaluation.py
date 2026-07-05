"""P0-3: the prompt asks the agent to OPEN its reasoning with an `Assessment:` of what the last action
did (grounded in the fresh observation + `*`-new elements + last result). When present we surface it
as its own cockpit signal. It is NOT retry-enforced — a full LLM re-call to nudge a formatting label
would double cost; the prompt + the emitted signal carry the value, and stuck-detection already
catches no-effect actions."""
from langchain_core.messages import HumanMessage

from app.agent.nodes.reason import build_reason_node
from app.agent.state import AgentState
from app.events.emitter import EventEmitter
from app.events.protocol import EVALUATION
from app.events.sink import BufferSink
from tests.fakes.fake_llm import FakeLLMClient, ai

_CLICK = [{"name": "Click", "args": {"index": 1}, "id": "1"}]


def _state(step, **kw):
    return AgentState(task="t", thread_id="t1", step=step,
                      messages=[HumanMessage(content="page")], **kw)


async def _reason(llm, state):
    sink = BufferSink()
    node = build_reason_node(llm, EventEmitter(sink))
    delta = await node(state)
    return delta, sink


async def test_assessment_line_is_parsed_and_emitted():
    llm = FakeLLMClient(turns=[ai("Assessment: the login modal opened as expected.\nDecide: type email.", _CLICK)])
    delta, sink = await _reason(llm, _state(step=1))
    evals = [e.data["text"] for e in sink.events if e.event == EVALUATION]
    assert evals == ["the login modal opened as expected."]
    assert delta["step"] == 2


async def test_missing_assessment_does_not_retry_or_emit():
    # Reasoning present but no Assessment label — proceed on ONE call, emit nothing (no cost doubling).
    llm = FakeLLMClient(turns=[ai("I'll click the next button.", _CLICK)])
    delta, sink = await _reason(llm, _state(step=1))
    assert len(llm.calls) == 1
    assert delta.get("status") != "failed"
    assert delta["messages"][0].tool_calls[0]["name"] == "Click"
    assert not [e for e in sink.events if e.event == EVALUATION]


async def test_first_turn_emits_no_assessment():
    llm = FakeLLMClient(turns=[ai("Decide: navigate to the login page.", _CLICK)])
    delta, sink = await _reason(llm, _state(step=0))
    assert len(llm.calls) == 1
    assert delta["step"] == 1
    assert not [e for e in sink.events if e.event == EVALUATION]
