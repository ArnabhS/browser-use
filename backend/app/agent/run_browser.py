from __future__ import annotations

from app.agent.demo import run
from app.browser.local_cdp import LocalCDPSession
from app.config.container import build_default_app


async def run_on_html(html: str, task: str, llm, *, thread_id: str = "browser"):
    """Test helper: launch a LocalCDPSession, set HTML content, run the agent, stop.

    Mirrors the real-browser e2e flow in a single call — useful for integration
    smoke tests that need a full stack without a fixture HTTP server.
    """
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content(html)
        graph, *_ = build_default_app(session=sess, llm=llm)
        return await run(graph, task=task, thread_id=thread_id)
    finally:
        await sess.stop()
