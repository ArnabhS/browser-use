from langchain_core.messages import AIMessage
from app.agent.state import AgentState
from app.agent.routing import route_after_reason, route_after_act
from app.telemetry.records import ErrorCode


def _s(**kw):
    return AgentState(task="t", thread_id="t1", **kw)


def test_route_to_act_when_tool_calls_present():
    s = _s(step=1)
    s.messages = [AIMessage(content="go", tool_calls=[{"name": "Click", "args": {"index": 1}, "id": "1"}])]
    assert route_after_reason(s) == "act"


def test_route_nudge_then_fail_no_action():
    s = _s(step=1)
    s.messages = [AIMessage(content="hmm", tool_calls=[])]
    assert route_after_reason(s) == "reason"            # first time: nudge
    s.nudge_count = 1
    assert route_after_reason(s) == "finalize"          # second time: give up


def test_route_max_steps_to_finalize():
    s = _s(step=99)
    s.messages = [AIMessage(content="go", tool_calls=[{"name": "Click", "args": {"index": 1}, "id": "1"}])]
    assert route_after_reason(s, max_steps=25) == "finalize"


def test_route_after_act_finished_vs_observe():
    assert route_after_act(_s(finished=True)) == "finalize"
    assert route_after_act(_s(finished=False)) == "observe"


def test_route_after_reason_failed_status_finalizes():
    s = _s(status="failed", error_code=ErrorCode.REASONING_MISSING, finished=True)
    s.messages = [AIMessage(content="", tool_calls=[])]
    assert route_after_reason(s) == "finalize"
