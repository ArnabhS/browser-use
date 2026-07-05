"""P0-2: mark elements that appeared since the last action with `*[N]`, so the model knows its click
opened the dropdown/modal/autocomplete. The diff lives in the observe node (works for any
BrowserSession impl); nothing is 'new' on a fresh page or the first turn."""
from browser_agent_contracts import Element, Observation, Viewport

from app.agent.format import format_observation
from app.agent.nodes.observe import build_observe_node
from app.agent.state import AgentState
from app.events.emitter import EventEmitter
from app.events.sink import BufferSink
from tests.fakes.fake_browser import FakeBrowserSession


def _obs(url, elements):
    return Observation(url=url, viewport=Viewport(width=1, height=1), elements=elements)


def test_format_marks_new_elements_with_star_and_legend():
    obs = _obs("https://x", [
        Element(index=1, role="button", name="Go"),
        Element(index=2, role="dialog", name="Close", is_new=True),
    ])
    text = format_observation(obs)
    assert "*[2] dialog" in text and '"Close"' in text
    assert "[1] button" in text and "*[1]" not in text     # unchanged element not starred
    assert "appeared" in text.lower()                       # legend explains the marker


def test_format_no_legend_when_nothing_is_new():
    obs = _obs("https://x", [Element(index=1, role="button", name="Go")])
    text = format_observation(obs)
    assert "*[" not in text and "appeared" not in text.lower()


async def _run(prev, curr):
    node = build_observe_node(FakeBrowserSession(observations=[curr]), EventEmitter(BufferSink()))
    return await node(AgentState(task="t", thread_id="t1", observation=prev))


async def test_observe_marks_element_absent_last_turn_as_new():
    prev = _obs("https://x", [Element(index=1, role="button", name="Go")])
    curr = _obs("https://x", [Element(index=1, role="button", name="Go"),
                              Element(index=2, role="dialog", name="Close")])
    delta = await _run(prev, curr)
    flags = {e.name: e.is_new for e in delta["observation"].elements}
    assert flags == {"Go": False, "Close": True}
    assert "*[2] dialog" in delta["messages"][0].content    # rendered into the message too


async def test_observe_url_change_marks_nothing_new():
    prev = _obs("https://x", [Element(index=1, role="button", name="Go")])
    curr = _obs("https://y", [Element(index=1, role="link", name="Home")])
    delta = await _run(prev, curr)
    assert all(not e.is_new for e in delta["observation"].elements)


async def test_observe_first_turn_marks_nothing_new():
    curr = _obs("https://x", [Element(index=1, role="button", name="Go")])
    delta = await _run(None, curr)
    assert all(not e.is_new for e in delta["observation"].elements)
