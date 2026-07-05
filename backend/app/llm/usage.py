from __future__ import annotations

from app.events.emitter import EventEmitter
from app.events.protocol import USAGE
from app.telemetry.records import StepRecord


class UsageTracker:
    """Accumulates per-call LLM usage and renders StepRecords + USAGE events."""

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.cached_tokens = 0
        self.calls = 0

    def record(self, model_name: str, usage_metadata: dict | None, latency_ms: float) -> StepRecord:
        u = usage_metadata or {}
        inp = int(u.get("input_tokens", 0))
        out = int(u.get("output_tokens", 0))
        # langchain 1.x surfaces OpenRouter/Anthropic prompt-cache reads here (billed ~0.25x).
        details = u.get("input_token_details") or {}
        cached = int(details.get("cache_read", 0) or 0)
        self.input_tokens += inp
        self.output_tokens += out
        self.cached_tokens += cached
        self.calls += 1
        return StepRecord(step=0, node="llm", input_tokens=inp, output_tokens=out,
                          cached_tokens=cached, latency_ms=latency_ms, model=model_name)

    def totals(self) -> dict:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "cached_tokens": self.cached_tokens, "calls": self.calls}

    async def emit(self, emitter: EventEmitter, record: StepRecord) -> None:
        await emitter._emit(  # noqa: SLF001 — intentional internal dispatch
            USAGE,
            {
                "model": record.model,
                "inputTokens": record.input_tokens,
                "outputTokens": record.output_tokens,
                "cachedTokens": record.cached_tokens,
                "latencyMs": record.latency_ms,
            },
        )
