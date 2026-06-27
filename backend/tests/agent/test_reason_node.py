from langchain_core.messages import AIMessage, HumanMessage
from app.agent.state import AgentState
from app.agent.nodes.reason import build_reason_node
from app.events.emitter import EventEmitter
from app.events.sink import BufferSink
from app.telemetry.records import ErrorCode
from tests.fakes.fake_llm import FakeLLMClient, ai


async def test_reason_emits_ai_message_with_tool_call():
    llm = FakeLLMClient(turns=[ai("I will click Login", [{"name": "Click", "args": {"index": 1}, "id": "1"}])])
    node = build_reason_node(llm, EventEmitter(BufferSink()))
    state = AgentState(task="t", thread_id="t1", messages=[HumanMessage(content="page")])
    delta = await node(state)
    assert delta["step"] == 1
    assert delta["messages"][0].tool_calls[0]["name"] == "Click"


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
    assert llm.calls == 2  # retried exactly once
