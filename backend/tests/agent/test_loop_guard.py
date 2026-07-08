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


def test_sig_keys_on_element_identity_not_churning_index():
    # MakeMyTrip renumbers [N] every turn, so the SAME "SEARCH" button was [66], then [60], then
    # [56]. Keyed by raw index, those re-clicks never collide and the loop guard is blind.
    url = "https://www.makemytrip.com/"
    a = _action_sig(ActionCall(name="click", args={"index": 66}), url, target="button:SEARCH")
    b = _action_sig(ActionCall(name="click", args={"index": 56}), url, target="button:SEARCH")
    assert a == b


def test_sig_distinguishes_different_elements_that_reuse_an_index():
    # The converse hazard: index 31 was "Round Trip" one turn and something else the next —
    # clicking both is progress, not a loop.
    url = "https://www.makemytrip.com/"
    a = _action_sig(ActionCall(name="click", args={"index": 31}), url, target="radio:Round Trip")
    b = _action_sig(ActionCall(name="click", args={"index": 31}), url, target="button:APPLY")
    assert a != b


async def test_act_node_sigs_carry_element_identity_from_the_observation():
    from langchain_core.messages import AIMessage

    from app.agent.nodes.act import build_act_node
    from app.telemetry.store import InMemoryTrajectoryStore
    from app.tools.dispatcher import ToolDispatcher
    from browser_agent_contracts import Element, Observation, Viewport
    from tests.fakes.fake_browser import FakeBrowserSession

    obs = Observation(url="https://x.test/", title="t", viewport=Viewport(width=1280, height=800),
                      elements=[Element(index=66, role="button", name="SEARCH")])
    s = AgentState(task="t", thread_id="t1", observation=obs)
    s.messages = [AIMessage(content="go", tool_calls=[{"name": "Click", "args": {"index": 66}, "id": "1"}])]
    node = build_act_node(ToolDispatcher(), FakeBrowserSession(), EventEmitter(BufferSink()),
                          InMemoryTrajectoryStore())
    delta = await node(s)
    assert "button:SEARCH" in delta["recent_actions"][-1]


async def test_degenerate_runaway_reasoning_is_clipped_before_entering_history():
    # Observed live (MakeMyTrip): the model degenerated into "Let's click [56]. " repeated hundreds
    # of times. Stored verbatim, that blob is re-sent every later turn and feeds the repetition.
    runaway = "Let's click [56]. " * 3000                      # ~54k chars
    llm = FakeLLMClient(turns=[ai(runaway, _CLICK)])
    delta = await _reason(llm, _state([]))
    stored = delta["messages"][0]
    assert len(stored.content) < 5000
    assert stored.tool_calls  # the action itself must survive the clip


def _state_at(step: int):
    return AgentState(task="t", thread_id="t1", step=step, messages=[HumanMessage(content="page")])


async def test_budget_warning_injected_when_steps_running_low():
    # Near the step cap, the agent must be told to report partial findings via Complete rather than
    # run out with nothing reported (the maxsteps-with-empty-hands failure mode).
    llm = FakeLLMClient(turns=[ai("assess; decide", _CLICK)])
    node = build_reason_node(llm, EventEmitter(BufferSink()), max_steps=10)
    delta = await node(_state_at(7))                 # 3 steps left
    assert delta.get("status") != "failed"
    sent = llm.calls[0]
    assert any(isinstance(m, HumanMessage) and "step" in m.content.lower() and "complete" in m.content.lower()
               for m in sent)


async def test_no_budget_warning_when_plenty_of_steps():
    llm = FakeLLMClient(turns=[ai("assess; decide", _CLICK)])
    node = build_reason_node(llm, EventEmitter(BufferSink()), max_steps=60)
    await node(_state_at(3))                          # 57 steps left
    assert not any(isinstance(m, HumanMessage) and "steps left" in m.content.lower()
                   for m in llm.calls[0])
