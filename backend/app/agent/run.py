from __future__ import annotations

import asyncio

from app.agent.demo import run
from app.agent.state import AgentState
from app.config.container import build_default_app
from tests.fakes.fake_browser import FakeBrowserSession  # B2-only: replaced by the real LocalCDPSession browser in B3


async def run_task(task: str, *, thread_id: str = "live") -> AgentState:
    """Run the agent with the REAL OpenRouter LLM against a fake browser (B2)."""
    graph, emitter, store, sink, memory = build_default_app(session=FakeBrowserSession())
    return await run(graph, task=task, thread_id=thread_id, memory=memory)


async def _main() -> None:
    final = await run_task("Decide there's nothing to do and call Complete(success=true, reason='noop').")
    print(f"status={final.status} success={final.success} reason={final.reason!r} steps={final.step}")


if __name__ == "__main__":
    asyncio.run(_main())
