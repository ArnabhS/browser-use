"""Task 5: observations are tagged in observe, compacted in reason, context_status emitted."""
from app.agent.demo import run
from app.config.container import build_default_app
from tests.fakes.fake_browser import FakeBrowserSession
from tests.fakes.fake_llm import FakeLLMClient, ai


async def test_old_observations_not_sent_to_llm_and_status_emitted():
    # 3 LLM turns so >1 observation accumulates before the final call
    llm = FakeLLMClient(turns=[
        ai("scroll", [{"name": "Scroll", "args": {"direction": "down"}, "id": "t1"}]),
        ai("scroll", [{"name": "Scroll", "args": {"direction": "down"}, "id": "t2"}]),
        ai("done", [{"name": "Complete", "args": {"success": True, "reason": "ok"}, "id": "c1"}]),
    ])
    graph, emitter, store, sink, _ = build_default_app(session=FakeBrowserSession(), llm=llm)
    await run(graph, task="t", thread_id="tc")

    # the LLM never received more than one observation message in any single call
    for call in llm.calls:
        obs = [m for m in call if getattr(m, "name", None) == "observation"]
        assert len(obs) <= 1, f"Got {len(obs)} observation(s) in one LLM call — compaction failed"

    # a context_status event was emitted
    assert any(ev.event == "context_status" for ev in sink.events), (
        "No context_status event found in sink; emitter.emit_context_status not wired"
    )

    # the first message after the system message is never an AIMessage (user-role-first guard)
    from langchain_core.messages import AIMessage
    for call in llm.calls:
        assert not isinstance(call[1], AIMessage), (
            "First non-system message in LLM call is an AIMessage — user-role-first guard failed"
        )
