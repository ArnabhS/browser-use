"""The agent must not loop forever on an action that has no effect (clicking a dead element)."""
from app.agent.demo import run
from app.config.container import build_default_app
from app.telemetry.records import ErrorCode
from tests.fakes.fake_browser import FakeBrowserSession
from tests.fakes.fake_llm import FakeLLMClient, ai


async def test_repeated_noop_action_fails_with_stuck():
    # The LLM clicks the same index forever; the fake page never changes => the loop is detected.
    turns = [ai("clicking it", [{"name": "Click", "args": {"index": 1}, "id": f"c{i}"}]) for i in range(20)]
    graph, emitter, store, sink, _ = build_default_app(
        session=FakeBrowserSession(), llm=FakeLLMClient(turns=turns)
    )
    final = await run(graph, task="click the same thing forever", thread_id="stuck")

    assert final.status == "failed"
    assert final.error_code == ErrorCode.STUCK
    assert final.step < 20  # bailed early instead of burning the whole step budget


async def test_progress_resets_stuck(monkeypatch):
    # A run that completes normally must not be flagged stuck.
    turns = [
        ai("clicking", [{"name": "Click", "args": {"index": 1}, "id": "c1"}]),
        ai("done", [{"name": "Complete", "args": {"success": True, "reason": "ok"}, "id": "d1"}]),
    ]
    graph, emitter, store, sink, _ = build_default_app(
        session=FakeBrowserSession(), llm=FakeLLMClient(turns=turns)
    )
    final = await run(graph, task="quick", thread_id="ok")
    assert final.status == "done" and final.success is True
