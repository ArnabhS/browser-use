import pytest
from browser_agent_contracts import ActionCall, ActionResult, Observation, Viewport
from langchain_core.messages import ToolMessage

from app.agent.state import AgentState
from app.events.emitter import EventEmitter
from app.events.sink import BufferSink
from app.tools.dispatcher import ToolDispatcher


class _RecordingSession:
    def __init__(self):
        self.calls: list[ActionCall] = []

    async def observe(self, *, include_som=True):
        return Observation(url="about:blank", viewport=Viewport(width=1, height=1))

    async def act(self, call: ActionCall) -> ActionResult:
        self.calls.append(call)
        return ActionResult(success=True, reason=f"did {call.name}")

    async def navigate(self, url):
        return ActionResult(success=True, reason="nav")

    async def tabs(self):
        return []


def _state():
    return AgentState(task="t", thread_id="t1")


async def test_click_builds_actioncall_and_calls_session():
    d = ToolDispatcher()
    sess = _RecordingSession()
    msg, delta = await d.dispatch(
        {"name": "Click", "args": {"index": 5}, "id": "c1"},
        state=_state(), session=sess, emitter=EventEmitter(BufferSink()),
    )
    assert sess.calls[0] == ActionCall(name="click", args={"index": 5})
    assert isinstance(msg, ToolMessage) and msg.tool_call_id == "c1"
    assert delta["last_action"].name == "click" and delta["last_result"].success is True


async def test_remember_merges_into_agent_memory():
    d = ToolDispatcher()
    msg, delta = await d.dispatch(
        {"name": "Remember", "args": {"key": "login_url", "value": "/auth"}, "id": "r1"},
        state=_state(), session=_RecordingSession(), emitter=EventEmitter(BufferSink()),
    )
    assert delta["agent_memory"] == {"login_url": "/auth"}
    assert "login_url" in msg.content


async def test_complete_sets_terminal_fields():
    d = ToolDispatcher()
    msg, delta = await d.dispatch(
        {"name": "Complete", "args": {"success": True, "reason": "logged in"}, "id": "k1"},
        state=_state(), session=_RecordingSession(), emitter=EventEmitter(BufferSink()),
    )
    assert delta == {"finished": True, "success": True, "reason": "logged in"}
