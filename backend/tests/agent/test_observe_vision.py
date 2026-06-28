from browser_agent_contracts import Element, Observation, Viewport
from langchain_core.messages import HumanMessage
from app.agent.state import AgentState
from app.agent.nodes.observe import build_observe_node
from app.events.emitter import EventEmitter
from app.events.sink import BufferSink
from tests.fakes.fake_browser import FakeBrowserSession


def _obs():
    return Observation(url="https://x", viewport=Viewport(width=1, height=1),
                       elements=[Element(index=1, role="button", name="Go")])


async def test_vision_off_emits_text_only():
    node = build_observe_node(FakeBrowserSession(observations=[_obs()]), EventEmitter(BufferSink()), use_vision=False)
    delta = await node(AgentState(task="t", thread_id="t1"))
    assert isinstance(delta["messages"][0].content, str)


async def test_vision_on_attaches_image_block():
    sess = FakeBrowserSession(observations=[_obs()], latest_screenshot=b"\x89PNGfake")
    node = build_observe_node(sess, EventEmitter(BufferSink()), use_vision=True)
    delta = await node(AgentState(task="t", thread_id="t1"))
    content = delta["messages"][0].content
    assert isinstance(content, list)
    assert content[0]["type"] == "text" and "[1] button" in content[0]["text"]
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
