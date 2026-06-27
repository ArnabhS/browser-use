from browser_agent_contracts import Element, Observation, Viewport
from langchain_core.messages import HumanMessage
from app.agent.state import AgentState
from app.agent.format import format_observation
from app.agent.nodes.observe import build_observe_node
from app.events.emitter import EventEmitter
from app.events.sink import BufferSink
from tests.fakes.fake_browser import FakeBrowserSession


def test_format_observation_numbers_elements():
    obs = Observation(
        url="https://x", title="X", viewport=Viewport(width=1, height=1),
        elements=[Element(index=1, role="button", name="Login"),
                  Element(index=2, role="textbox", name="Email")],
    )
    text = format_observation(obs)
    assert "https://x" in text and "[1] button" in text and "Login" in text and "[2] textbox" in text


async def test_observe_node_writes_observation_and_message():
    obs = Observation(url="https://x", viewport=Viewport(width=1, height=1),
                      elements=[Element(index=1, role="button", name="Go")])
    sink = BufferSink()
    node = build_observe_node(FakeBrowserSession(observations=[obs]), EventEmitter(sink))
    delta = await node(AgentState(task="t", thread_id="t1"))
    assert delta["observation"].url == "https://x"
    assert isinstance(delta["messages"][0], HumanMessage) and "[1] button" in delta["messages"][0].content
    assert delta["history"][0].node == "observe"
    assert any(e.type == "observation" for e in sink.events)
