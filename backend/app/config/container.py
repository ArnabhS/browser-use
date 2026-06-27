from __future__ import annotations

from app.agent.graph import build_graph
from app.config.settings import get_settings
from app.events.emitter import EventEmitter
from app.events.sink import BufferSink, EventSink
from app.telemetry.store import InMemoryTrajectoryStore


def build_default_app(*, session, llm, sink: EventSink | None = None):
    """Composition root (B1): wire a graph from injected fakes/concretes."""
    settings = get_settings()
    sink = sink or BufferSink()
    emitter = EventEmitter(sink)
    store = InMemoryTrajectoryStore()
    graph = build_graph(session=session, llm=llm, emitter=emitter, store=store,
                        max_steps=settings.max_steps)
    return graph, emitter, store, sink
