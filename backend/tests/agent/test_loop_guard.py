"""Action-repetition loop guard: the page-signature stuck_count misses loops where the page
superficially changes (clear/retype, flickering dropdowns) but the agent keeps firing the SAME
committing action. Detect that from recent_actions and nudge hard, then break."""
from langchain_core.messages import HumanMessage

from app.agent.nodes.act import _action_sig
from app.agent.nodes.reason import build_reason_node
from app.agent.state import AgentState
from app.events.emitter import EventEmitter
from app.events.sink import BufferSink
from app.telemetry.records import ErrorCode
from browser_agent_contracts import ActionCall
from tests.fakes.fake_llm import FakeLLMClient, ai

_CLICK = [{"name": "Click", "args": {"index": 1}, "id": "1"}]


async def _reason(llm, state):
    return await build_reason_node(llm, EventEmitter(BufferSink()))(state)


def _state(recent, **kw):
    return AgentState(task="t", thread_id="t1", step=3, recent_actions=recent,
                      messages=[HumanMessage(content="page")], **kw)


async def test_repeated_action_hard_fails_as_stuck_before_calling_llm():
    llm = FakeLLMClient(turns=[ai("x", _CLICK)])
    delta = await _reason(llm, _state(['type:{"index": 3, "text": "hi"}'] * 5))
    assert delta["status"] == "failed" and delta["error_code"] == ErrorCode.STUCK
    assert delta["finished"] is True
    assert len(llm.calls) == 0  # broke without spending another LLM call


async def test_repeated_action_nudges_at_three():
    llm = FakeLLMClient(turns=[ai("assess; try something different", _CLICK)])
    delta = await _reason(llm, _state(['click:{"index": 5}'] * 3))
    assert delta.get("status") != "failed"
    assert delta["nudge_count"] == 1
    sent = llm.calls[0]
    assert any(isinstance(m, HumanMessage) and "same action" in m.content.lower() for m in sent)


async def test_diverse_actions_do_not_trigger_the_loop_guard():
    llm = FakeLLMClient(turns=[ai("assess; click", _CLICK)])
    recent = ['click:{"index": 1}', 'type:{"index": 2}', 'click:{"index": 3}', 'navigate:{"url": "x"}']
    delta = await _reason(llm, _state(recent))
    assert delta.get("status") != "failed"
    assert delta.get("nudge_count", 0) == 0
    assert not any("same action" in m.content.lower()
                   for m in llm.calls[0] if isinstance(m, HumanMessage))


def test_same_action_on_different_pages_is_not_a_loop():
    # Metacritic: clicking the always-index-9 autocomplete result navigates to a NEW show page each
    # time — real progress, not a repeat. The signature must distinguish them by the acted-on page.
    a = ActionCall(name="click", args={"index": 9})
    assert _action_sig(a, "https://metacritic.com/tv/i-will-find-you/") \
        != _action_sig(a, "https://metacritic.com/tv/the-season-2026/")


def test_same_action_on_same_page_is_a_loop():
    # bbcgoodfood: re-clicking the same dead index on the same URL IS a loop — sigs must collide.
    a = ActionCall(name="click", args={"index": 64})
    url = "https://bbcgoodfood.com/search?q=Keto"
    assert _action_sig(a, url) == _action_sig(a, url)
