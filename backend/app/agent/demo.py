from __future__ import annotations

import asyncio

from app.agent.state import AgentState


async def run(graph, task: str, thread_id: str = "demo") -> AgentState:
    """Astream the graph to completion; return the final AgentState.

    Input is a plain dict (the documented LangGraph input form) — the graph fills
    the AgentState defaults. `aget_state(config).values` is a dict we re-validate.
    """
    config = {"configurable": {"thread_id": thread_id}}
    async for _ in graph.astream(
        {"task": task, "thread_id": thread_id}, config=config, stream_mode="updates"
    ):
        pass
    snapshot = await graph.aget_state(config)
    return AgentState.model_validate(snapshot.values)


async def _demo() -> None:
    from app.config.container import build_default_app
    from tests.fakes.fake_browser import FakeBrowserSession
    from tests.fakes.fake_llm import FakeLLMClient, ai

    llm = FakeLLMClient(turns=[
        ai("I'll click Login", [{"name": "Click", "args": {"index": 1}, "id": "a"}]),
        ai("Done", [{"name": "Complete", "args": {"success": True, "reason": "done"}, "id": "b"}]),
    ])
    graph, emitter, store, sink = build_default_app(session=FakeBrowserSession(), llm=llm)
    final = await run(graph, task="log in (fake demo)", thread_id="demo")
    print(f"status={final.status} success={final.success} reason={final.reason!r}")
    for ev in sink.events:
        print(f"  · {ev.event}: {ev.data}")


if __name__ == "__main__":
    asyncio.run(_demo())
