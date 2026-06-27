import pytest
from browser_agent_contracts import ActionCall, Observation, Viewport
from app.browser.base import BrowserSession
from app.llm.base import LLMClient
from tests.fakes.fake_browser import FakeBrowserSession
from tests.fakes.fake_llm import FakeLLMClient, ai


async def test_fake_browser_satisfies_port_and_records_acts():
    obs = Observation(url="https://x", viewport=Viewport(width=2, height=2))
    sess = FakeBrowserSession(observations=[obs])
    assert isinstance(sess, BrowserSession)
    assert (await sess.observe()).url == "https://x"
    await sess.act(ActionCall(name="click", args={"index": 1}))
    assert sess.acts[0].args["index"] == 1


async def test_fake_llm_pops_scripted_turns():
    llm = FakeLLMClient(turns=[ai("thinking", [{"name": "Complete", "args": {"success": True, "reason": "ok"}, "id": "1"}])])
    assert isinstance(llm, LLMClient)
    msg = await llm.complete(messages=[], tools=[])
    assert msg.tool_calls[0]["name"] == "Complete"
    with pytest.raises(IndexError):
        await llm.complete(messages=[], tools=[])
