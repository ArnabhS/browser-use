import pytest
from browser_agent_contracts import Observation
from app.browser.local_cdp import LocalCDPSession
from app.config.container import build_default_app
from app.agent.demo import run
from tests.fakes.fake_llm import FakeLLMClient, ai

pytestmark = pytest.mark.browser

_HTML = """
<html><body>
  <button onclick="document.title='DONE'">Finish</button>
</body></html>
"""


async def test_agent_clicks_real_button_then_completes():
    sess = LocalCDPSession()
    await sess.start()
    try:
        await sess.page.set_content(_HTML)
        first = await sess.observe()                       # peek to learn the button index
        idx = next(e.index for e in first.elements if e.name == "Finish")
        llm = FakeLLMClient(turns=[
            ai("I'll click Finish", [{"name": "Click", "args": {"index": idx}, "id": "a"}]),
            ai("Title changed; done", [{"name": "Complete", "args": {"success": True, "reason": "done"}, "id": "b"}]),
        ])
        graph, *_ = build_default_app(session=sess, llm=llm)
        final = await run(graph, task="click finish", thread_id="rb1")
        assert final.status == "done" and final.success is True
        assert await sess.page.title() == "DONE"           # the agent really clicked it
    finally:
        await sess.stop()
