from __future__ import annotations

import asyncio
import time
from typing import Sequence

from langchain_core.messages import AIMessage, BaseMessage
from pydantic import BaseModel

from app.events.emitter import EventEmitter
from app.llm.usage import UsageTracker

_TRANSIENT_STATUS = {429, 500, 502, 503, 504}


def _network_exc_types() -> tuple:
    types: tuple = (asyncio.TimeoutError,)
    try:
        import httpx
        types += (httpx.TransportError,)
    except Exception:
        pass
    try:
        from openai import APIConnectionError, APITimeoutError
        types += (APIConnectionError, APITimeoutError)
    except Exception:
        pass
    return types


_NETWORK_EXC = _network_exc_types()


def _status_of(exc: Exception) -> int | None:
    for attr in ("status_code", "http_status", "code"):
        v = getattr(exc, attr, None)
        if isinstance(v, int):
            return v
    resp = getattr(exc, "response", None)
    return getattr(resp, "status_code", None) if resp is not None else None


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, _NETWORK_EXC):
        return True
    return _status_of(exc) in _TRANSIENT_STATUS


def _retry_after(exc: Exception) -> float | None:
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None) or {}
    val = headers.get("Retry-After") or headers.get("retry-after")
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _chunk_text(chunk) -> str:
    c = getattr(chunk, "content", "")
    if isinstance(c, str):
        return c
    return "".join(b.get("text", "") for b in c if isinstance(b, dict))


class OpenRouterLLMClient:
    """LLMClient over a bind_tools'd ChatOpenAI Runnable: streams, meters, retries."""

    def __init__(self, model, emitter: EventEmitter, usage_tracker: UsageTracker,
                 *, max_retries: int = 3, model_name: str = "") -> None:
        self._model = model
        self._emitter = emitter
        self._usage = usage_tracker
        self._max_retries = max_retries
        self._model_name = model_name

    async def complete(self, *, messages: list[BaseMessage],
                       tools: Sequence[type[BaseModel]] = ()) -> AIMessage:
        attempt = 0
        while True:
            try:
                return await self._stream_once(messages)
            except Exception as exc:  # noqa: BLE001 — classify then re-raise
                attempt += 1
                if attempt > self._max_retries or not _is_transient(exc):
                    raise
                delay = _retry_after(exc) or min(2.0 ** attempt, 30.0)
                await asyncio.sleep(delay)

    async def _stream_once(self, messages: list[BaseMessage]) -> AIMessage:
        started = time.monotonic()
        full = None
        async for chunk in self._model.astream(messages):
            full = chunk if full is None else full + chunk
            await self._emitter.emit_stream(_chunk_text(chunk))
        latency_ms = (time.monotonic() - started) * 1000.0
        if full is None:
            raise RuntimeError("LLM produced no output")
        record = self._usage.record(self._model_name, getattr(full, "usage_metadata", None), latency_ms)
        await self._usage.emit(self._emitter, record)
        return AIMessage(
            content=full.content,
            tool_calls=list(getattr(full, "tool_calls", []) or []),
            usage_metadata=getattr(full, "usage_metadata", None),
            response_metadata=getattr(full, "response_metadata", {}) or {},
        )
