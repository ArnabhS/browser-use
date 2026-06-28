from app.events.sink import BufferSink
from app.events.emitter import EventEmitter
from app.events.protocol import TOOL_CALL, REASONING, QUESTION


async def test_emitter_pushes_typed_events_to_sink():
    sink = BufferSink()
    em = EventEmitter(sink)
    await em.emit_reasoning("I will click login")
    await em.emit_tool_call("Click", {"index": 5})
    types = [e.event for e in sink.events]
    assert types == [REASONING, TOOL_CALL]
    assert sink.events[1].data == {"name": "Click", "args": {"index": 5}}
    assert isinstance(sink.events[0].ts, str) and sink.events[0].ts


async def test_emit_question_pushes_question_event():
    sink = BufferSink()
    em = EventEmitter(sink)
    await em.emit_question("creds?", "need login")
    assert len(sink.events) == 1
    assert sink.events[0].event == QUESTION
    assert sink.events[0].data == {"question": "creds?", "context": "need login"}
