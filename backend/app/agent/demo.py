from __future__ import annotations

import asyncio

from langgraph.types import Command

from app.agent.state import AgentState


async def run(
    graph,
    task: str,
    thread_id: str = "demo",
    *,
    answer_provider=None,
    emitter=None,
    memory=None,
) -> AgentState:
    """Astream the graph to completion, pausing on AskUser interrupts.

    On each LangGraph `interrupt`, emit a QUESTION event (if an emitter is given),
    ask `answer_provider(question_dict) -> str` for the answer, and resume with it.
    Without a provider, a safe default answer is supplied so the run still finishes.

    If `memory` is provided, preloads `agent_memory` from the store before streaming
    and manages start/stop lifecycle around the run.

    Interrupt detection (LangGraph 1.0.9, stream_mode="updates"):
      Chunks are plain dicts; an interrupt chunk looks like
        {"__interrupt__": (Interrupt(value=..., id=...), ...)}
      We check `"__interrupt__" in chunk` and read `.value` from the first object.
      Fallback: `(await graph.aget_state(config)).interrupts` (same Interrupt objects).
    """
    config = {"configurable": {"thread_id": thread_id}}
    preload = await memory.load(thread_id) if memory is not None else {}
    if memory is not None:
        await memory.start()
    try:
        stream_input: object = {"task": task, "thread_id": thread_id, "agent_memory": preload}
        while True:
            interrupt_value = None
            async for chunk in graph.astream(stream_input, config=config, stream_mode="updates"):
                if isinstance(chunk, dict) and "__interrupt__" in chunk:
                    interrupt_value = chunk["__interrupt__"][0].value
            if interrupt_value is None:
                break
            q = interrupt_value if isinstance(interrupt_value, dict) else {"question": str(interrupt_value)}
            if emitter is not None:
                await emitter.emit_question(q.get("question", ""), q.get("context", ""))
            if answer_provider is not None:
                answer = await answer_provider(q)
            else:
                answer = "No answer available; proceed with your best judgment."
            stream_input = Command(resume=answer)
    finally:
        if memory is not None:
            await memory.stop()
    snapshot = await graph.aget_state(config)
    return AgentState.model_validate(snapshot.values)


async def console_answer_provider(question: dict) -> str:
    """Print the agent's question and read one line from stdin (for live CLI runs)."""
    import asyncio as _asyncio
    ctx = question.get("context", "")
    print(f"\n❓ AGENT ASKS: {question.get('question', '')}" + (f"  ({ctx})" if ctx else ""))
    return (await _asyncio.get_event_loop().run_in_executor(None, input, "   your answer > ")).strip()


async def _demo() -> None:
    from app.config.container import build_default_app
    from tests.fakes.fake_browser import FakeBrowserSession
    from tests.fakes.fake_llm import FakeLLMClient, ai

    llm = FakeLLMClient(turns=[
        ai("I'll click Login", [{"name": "Click", "args": {"index": 1}, "id": "a"}]),
        ai("Done", [{"name": "Complete", "args": {"success": True, "reason": "done"}, "id": "b"}]),
    ])
    graph, emitter, store, sink, _ = build_default_app(session=FakeBrowserSession(), llm=llm)
    final = await run(graph, task="log in (fake demo)", thread_id="demo")
    print(f"status={final.status} success={final.success} reason={final.reason!r}")
    for ev in sink.events:
        print(f"  · {ev.event}: {ev.data}")


if __name__ == "__main__":
    asyncio.run(_demo())
