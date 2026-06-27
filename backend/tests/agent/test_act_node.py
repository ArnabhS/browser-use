from langchain_core.messages import AIMessage, ToolMessage
from app.agent.state import AgentState
from app.agent.nodes.act import build_act_node
from app.tools.dispatcher import ToolDispatcher
from app.events.emitter import EventEmitter
from app.events.sink import BufferSink
from app.telemetry.store import InMemoryTrajectoryStore
from tests.fakes.fake_browser import FakeBrowserSession


def _state_with_toolcall(name, args, id="1"):
    s = AgentState(task="t", thread_id="t1")
    s.messages = [AIMessage(content="acting", tool_calls=[{"name": name, "args": args, "id": id}])]
    return s


async def test_act_dispatches_click_and_records():
    sess = FakeBrowserSession()
    store = InMemoryTrajectoryStore()
    node = build_act_node(ToolDispatcher(), sess, EventEmitter(BufferSink()), store)
    delta = await node(_state_with_toolcall("Click", {"index": 3}))
    assert isinstance(delta["messages"][0], ToolMessage)
    assert sess.acts[0].name == "click" and sess.acts[0].args["index"] == 3
    assert delta["last_action"].name == "click"
    assert store.records["t1"][0].node == "act"


async def test_act_complete_sets_finished():
    node = build_act_node(ToolDispatcher(), FakeBrowserSession(), EventEmitter(BufferSink()), InMemoryTrajectoryStore())
    delta = await node(_state_with_toolcall("Complete", {"success": True, "reason": "done"}))
    assert delta["finished"] is True and delta["success"] is True and delta["reason"] == "done"
