"""E2E tests for the AskUser interrupt/resume loop in app/agent/demo.run()."""
from __future__ import annotations

from app.agent.demo import run
from app.config.container import build_default_app
from tests.fakes.fake_browser import FakeBrowserSession
from tests.fakes.fake_llm import FakeLLMClient, ai


async def test_ask_user_pauses_gets_answer_and_resumes():
    llm = FakeLLMClient(turns=[
        ai("I need the OTP to continue", [
            {"name": "AskUser", "args": {"question": "What is the OTP?", "context": "login step"}, "id": "q1"},
        ]),
        ai("Got the code, finishing", [
            {"name": "Complete", "args": {"success": True, "reason": "used the OTP"}, "id": "c1"},
        ]),
    ])
    graph, emitter, store, sink, _ = build_default_app(session=FakeBrowserSession(), llm=llm)

    asked: list[dict] = []

    async def provider(q: dict) -> str:
        asked.append(q)
        return "123456"

    final = await run(graph, task="log in", thread_id="t-ask", answer_provider=provider, emitter=emitter)

    assert final.status == "done" and final.success is True
    assert asked and asked[0]["question"] == "What is the OTP?" and asked[0]["context"] == "login step"
    # the answer was injected back into the agent as the tool result
    assert any("User answered: 123456" in str(getattr(m, "content", "")) for m in final.messages)
    # a QUESTION event was emitted for the cockpit/event stream
    assert any(ev.event == "question" and ev.data.get("question") == "What is the OTP?" for ev in sink.events)


async def test_run_without_provider_still_finishes():
    llm = FakeLLMClient(turns=[
        ai("asking", [{"name": "AskUser", "args": {"question": "x?"}, "id": "q1"}]),
        ai("done", [{"name": "Complete", "args": {"success": True, "reason": "ok"}, "id": "c1"}]),
    ])
    graph, emitter, store, sink, _ = build_default_app(session=FakeBrowserSession(), llm=llm)
    final = await run(graph, task="t", thread_id="t-noprov")  # no provider
    assert final.status == "done"  # default answer supplied, run completes
