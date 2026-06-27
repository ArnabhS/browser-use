from app.llm.usage import UsageTracker
from app.events.emitter import EventEmitter
from app.events.sink import BufferSink
from app.events.protocol import USAGE


def test_record_accumulates_and_returns_step_record():
    u = UsageTracker()
    r1 = u.record("x/model", {"input_tokens": 10, "output_tokens": 5}, 120.0)
    u.record("x/model", {"input_tokens": 7, "output_tokens": 3}, 80.0)
    assert r1.node == "llm" and r1.input_tokens == 10 and r1.latency_ms == 120.0
    assert u.totals() == {"input_tokens": 17, "output_tokens": 8, "calls": 2}


def test_record_handles_missing_usage():
    u = UsageTracker()
    r = u.record("x/model", None, 50.0)
    assert r.input_tokens == 0 and r.output_tokens == 0


async def test_emit_pushes_usage_event():
    u = UsageTracker()
    sink = BufferSink()
    r = u.record("x/model", {"input_tokens": 4, "output_tokens": 2}, 10.0)
    await u.emit(EventEmitter(sink), r)
    assert sink.events[0].event == USAGE
    assert sink.events[0].data["inputTokens"] == 4 and sink.events[0].data["model"] == "x/model"


async def test_emit_uses_the_records_own_model_not_the_latest():
    u = UsageTracker()
    sink = BufferSink()
    r1 = u.record("model-a", {"input_tokens": 1, "output_tokens": 1}, 1.0)
    u.record("model-b", {"input_tokens": 2, "output_tokens": 2}, 1.0)
    await u.emit(EventEmitter(sink), r1)
    assert sink.events[0].data["model"] == "model-a"
