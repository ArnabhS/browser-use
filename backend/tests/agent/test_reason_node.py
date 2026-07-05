from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from app.agent.state import AgentState
from app.agent.nodes.reason import build_reason_node
from app.events.emitter import EventEmitter
from app.events.sink import BufferSink
from app.telemetry.records import ErrorCode
from tests.fakes.fake_llm import FakeLLMClient, ai


async def test_reason_inserts_working_memory_right_after_cached_system():
    llm = FakeLLMClient(turns=[ai("assess; click", [{"name": "Click", "args": {"index": 1}, "id": "1"}])])
    node = build_reason_node(llm, EventEmitter(BufferSink()))
    state = AgentState(task="t", thread_id="t1", agent_memory={"cart": "2 items"},
                       messages=[HumanMessage(content="page")])
    await node(state)
    sent = llm.calls[0]
    assert isinstance(sent[0], SystemMessage)                       # cached prefix first
    assert getattr(sent[1], "name", None) == "working_memory"       # memory right after, outside cache
    assert "cart: 2 items" in sent[1].content


async def test_reason_omits_memory_message_when_memory_empty():
    llm = FakeLLMClient(turns=[ai("assess; click", [{"name": "Click", "args": {"index": 1}, "id": "1"}])])
    node = build_reason_node(llm, EventEmitter(BufferSink()))
    state = AgentState(task="t", thread_id="t1", agent_memory={}, messages=[HumanMessage(content="page")])
    await node(state)
    assert not any(getattr(m, "name", None) == "working_memory" for m in llm.calls[0])


async def test_reason_emits_ai_message_with_tool_call():
    llm = FakeLLMClient(turns=[ai("I will click Login", [{"name": "Click", "args": {"index": 1}, "id": "1"}])])
    node = build_reason_node(llm, EventEmitter(BufferSink()))
    state = AgentState(task="t", thread_id="t1", messages=[HumanMessage(content="page")])
    delta = await node(state)
    assert delta["step"] == 1
    assert delta["messages"][0].tool_calls[0]["name"] == "Click"
    assert delta["history"][0].node == "reason"


async def test_reason_missing_reasoning_retries_then_fails():
    # both turns return a tool call with empty content -> REASONING_MISSING after one retry
    llm = FakeLLMClient(turns=[
        ai("", [{"name": "Click", "args": {"index": 1}, "id": "1"}]),
        ai("   ", [{"name": "Click", "args": {"index": 1}, "id": "2"}]),
    ])
    node = build_reason_node(llm, EventEmitter(BufferSink()))
    delta = await node(AgentState(task="t", thread_id="t1", messages=[HumanMessage(content="page")]))
    assert delta["status"] == "failed" and delta["error_code"] == ErrorCode.REASONING_MISSING
    assert delta["finished"] is True
    assert len(llm.calls) == 2  # retried exactly once


async def test_reason_nudges_on_reentry_without_tool_call():
    # Last message is an AIMessage with no tool calls -> nudge: increment nudge_count, then proceed.
    llm = FakeLLMClient(turns=[ai("now I'll click", [{"name": "Click", "args": {"index": 1}, "id": "1"}])])
    node = build_reason_node(llm, EventEmitter(BufferSink()))
    state = AgentState(task="t", thread_id="t1",
                       messages=[AIMessage(content="prev turn, no tool", tool_calls=[])])
    delta = await node(state)
    assert delta["nudge_count"] == 1
    assert delta["step"] == 1
    assert delta["messages"][0].tool_calls[0]["name"] == "Click"
