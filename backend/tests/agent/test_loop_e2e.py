from browser_agent_contracts import Element, Observation, Viewport
from app.config.container import build_default_app
from app.agent.demo import run
from tests.fakes.fake_browser import FakeBrowserSession
from tests.fakes.fake_llm import FakeLLMClient, ai


def _obs(n_elements=1):
    return Observation(url="https://app", title="App", viewport=Viewport(width=1, height=1),
                       elements=[Element(index=1, role="button", name="Login")][:n_elements])


async def test_happy_path_reaches_done_via_complete():
    # turn 1: click; turn 2: complete
    llm = FakeLLMClient(turns=[
        ai("I'll click Login", [{"name": "Click", "args": {"index": 1}, "id": "a"}]),
        ai("Logged in; finishing", [{"name": "Complete", "args": {"success": True, "reason": "done"}, "id": "b"}]),
    ])
    sess = FakeBrowserSession(observations=[_obs(), _obs()])
    graph, emitter, store, sink = build_default_app(session=sess, llm=llm)
    final = await run(graph, task="log in", thread_id="t1")
    assert final.status == "done" and final.success is True and final.reason == "done"
    assert sess.acts[0].name == "click"
    assert any(e.type == "finalize" for e in sink.events)
    assert any(r.node == "act" for r in store.records["t1"])


async def test_remember_persists_in_state_across_turns():
    llm = FakeLLMClient(turns=[
        ai("Note the login url", [{"name": "Remember", "args": {"key": "url", "value": "/auth"}, "id": "a"}]),
        ai("Done", [{"name": "Complete", "args": {"success": True, "reason": "ok"}, "id": "b"}]),
    ])
    graph, *_ = build_default_app(session=FakeBrowserSession(), llm=llm)
    final = await run(graph, task="t", thread_id="t2")
    assert final.agent_memory == {"url": "/auth"}


async def test_no_tool_call_nudges_then_fails_no_action():
    llm = FakeLLMClient(turns=[ai("hmm no action", []), ai("still nothing", [])])
    graph, emitter, store, sink = build_default_app(session=FakeBrowserSession(), llm=llm)
    final = await run(graph, task="t", thread_id="t3")
    assert final.status == "failed" and final.error_code is not None
    assert final.error_code.value == "NO_ACTION"
