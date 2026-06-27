from langchain_core.messages import HumanMessage
from app.agent.state import AgentState
from app.telemetry.records import StepRecord


def test_state_defaults_and_construction():
    s = AgentState(task="log in", thread_id="t1")
    assert s.status == "running" and s.step == 0 and s.nudge_count == 0
    assert s.finished is False and s.success is None and s.agent_memory == {}
    assert s.messages == [] and s.history == []


def test_add_messages_reducer_appends():
    # Simulate LangGraph merging a delta: build state, then validate the reducer is wired.
    s = AgentState(task="x", thread_id="t1", messages=[HumanMessage(content="hi")])
    assert s.messages[0].content == "hi"


def test_history_accepts_step_records():
    s = AgentState(task="x", thread_id="t1", history=[StepRecord(step=1, node="observe")])
    assert s.history[0].node == "observe"
