import pytest
from langchain_core.messages import AIMessageChunk, HumanMessage
from app.llm.base import LLMClient
from app.llm.openrouter import OpenRouterLLMClient, _is_transient
from app.llm.usage import UsageTracker
from app.events.emitter import EventEmitter
from app.events.sink import BufferSink
from app.events.protocol import STREAM


class _StubModel:
    """Mimics a bind_tools'd ChatOpenAI: astream yields AIMessageChunks."""
    def __init__(self, chunks, *, fail_times=0, exc=None):
        self._chunks = chunks
        self._fail_times = fail_times
        self._exc = exc
        self.calls = 0
    async def astream(self, messages):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._exc
        for c in self._chunks:
            yield c


def _chunks_for_click():
    # two text chunks then a tool-call chunk; summing reconstructs the full message
    return [
        AIMessageChunk(content="I will "),
        AIMessageChunk(content="click Login"),
        AIMessageChunk(content="", tool_calls=[{"name": "Click", "args": {"index": 1}, "id": "1"}]),
    ]


async def test_complete_streams_tokens_and_returns_message():
    sink = BufferSink()
    client = OpenRouterLLMClient(_StubModel(_chunks_for_click()), EventEmitter(sink), UsageTracker(), model_name="m")
    assert isinstance(client, LLMClient)
    msg = await client.complete(messages=[HumanMessage(content="hi")], tools=[])
    assert "click Login" in msg.content
    assert msg.tool_calls[0]["name"] == "Click"
    assert [e.data["token"] for e in sink.events if e.event == STREAM] == ["I will ", "click Login"]


async def test_complete_retries_transient_then_succeeds():
    err = RuntimeError("boom"); err.status_code = 503
    model = _StubModel(_chunks_for_click(), fail_times=1, exc=err)
    client = OpenRouterLLMClient(model, EventEmitter(BufferSink()), UsageTracker(), max_retries=2, model_name="m")
    msg = await client.complete(messages=[HumanMessage(content="hi")], tools=[])
    assert msg.tool_calls[0]["name"] == "Click" and model.calls == 2


async def test_non_transient_error_propagates():
    err = RuntimeError("bad request"); err.status_code = 400
    model = _StubModel(_chunks_for_click(), fail_times=1, exc=err)
    client = OpenRouterLLMClient(model, EventEmitter(BufferSink()), UsageTracker(), max_retries=3, model_name="m")
    with pytest.raises(RuntimeError):
        await client.complete(messages=[HumanMessage(content="hi")], tools=[])


def test_is_transient_classifier():
    e1 = RuntimeError(); e1.status_code = 429
    e2 = RuntimeError(); e2.status_code = 400
    assert _is_transient(e1) and not _is_transient(e2)
