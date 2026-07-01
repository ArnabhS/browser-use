"""The live-view feature streams browser frames as `frame` AgentEvents over the same socket the
run already uses. emit_frame must produce a well-formed event so the cockpit can render it."""
from app.events.emitter import EventEmitter
from app.events.protocol import FRAME


class _CaptureSink:
    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


async def test_emit_frame_produces_frame_event_with_data_and_meta():
    sink = _CaptureSink()
    em = EventEmitter(sink)

    await em.emit_frame("BASE64JPEG", {"url": "https://x.com"})

    assert len(sink.events) == 1
    ev = sink.events[0]
    assert ev.event == FRAME
    assert ev.data["data"] == "BASE64JPEG"
    assert ev.data["url"] == "https://x.com"
