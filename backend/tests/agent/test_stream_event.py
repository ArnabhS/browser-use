from app.events.sink import BufferSink
from app.events.emitter import EventEmitter
from app.events.protocol import STREAM


async def test_emit_stream_pushes_token_event():
    sink = BufferSink()
    await EventEmitter(sink).emit_stream("Hel")
    assert sink.events[0].event == STREAM
    assert sink.events[0].data == {"token": "Hel"}


async def test_emit_stream_skips_empty():
    sink = BufferSink()
    await EventEmitter(sink).emit_stream("")
    assert sink.events == []
