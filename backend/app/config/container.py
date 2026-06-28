from __future__ import annotations

from app.agent.graph import build_graph
from app.config.settings import get_settings
from app.events.emitter import EventEmitter
from app.events.sink import BufferSink, EventSink
from app.llm.usage import UsageTracker
from app.telemetry.store import InMemoryTrajectoryStore


def build_default_app(*, session, llm=None, sink: EventSink | None = None):
    """Composition root: real OpenRouter LLM when a key is set (and no llm injected), else the injected llm."""
    settings = get_settings()
    sink = sink or BufferSink()
    emitter = EventEmitter(sink)
    store = InMemoryTrajectoryStore()
    usage = UsageTracker()

    if llm is None:
        if not settings.openrouter_api_key:
            raise ValueError("No OPENROUTER_API_KEY set and no llm injected — cannot build the agent.")
        from app.llm.factory import build_chat_model
        from app.llm.openrouter import OpenRouterLLMClient
        llm = OpenRouterLLMClient(
            build_chat_model(settings), emitter, usage,
            max_retries=settings.llm_max_retries, model_name=settings.agent_model,
        )

    graph = build_graph(session=session, llm=llm, emitter=emitter, store=store, max_steps=settings.max_steps)
    return graph, emitter, store, sink
