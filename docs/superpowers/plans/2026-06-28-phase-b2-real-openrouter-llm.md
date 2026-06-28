# Phase B2 — Real OpenRouter LLM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Swap the B1 `FakeLLMClient` for a real **OpenRouter** `LLMClient` (`ChatOpenAI` behind the port) with **token streaming**, **per-call usage metering**, and **decomposed Jinja2 prompts** — so the agent reasons with a real model against the (still-fake) browser. Real browser is B3.

**Architecture:** A `ChatOpenAI(base_url=OpenRouter, stream_usage=True).bind_tools(TOOL_SPECS, parallel_tool_calls=True)` Runnable is wrapped by `OpenRouterLLMClient`, which `astream`s, accumulates the chunks into one `AIMessage` (carrying `tool_calls` + `usage_metadata`), streams tokens to the `EventEmitter`, meters usage, and retries transient errors. The `reason` node's system prompt moves from a hardcoded string to **decomposed Jinja2 templates** rendered by a `PromptLoader`. The composition root picks the real client when an `OPENROUTER_API_KEY` is present, else the fake.

**Tech Stack:** langchain-openai (`ChatOpenAI`), langchain-core (messages/Runnable), Jinja2, Pydantic v2, pytest/pytest-asyncio. (All already in `backend/pyproject.toml`.)

## Global Constraints

- Work in `backend/`; tests `cd backend && uv run pytest`. `asyncio_mode="auto"` is set — `async def test_*` runs.
- **OpenRouter is the only LLM gateway.** `ChatOpenAI(base_url=settings.openrouter_base_url, api_key=settings.openrouter_api_key, model=settings.agent_model, stream_usage=True)`. Keys are **server-side only** (already gitignored `.env`); never logged, never in events.
- **The graph/services see only the `LLMClient` port** — never LangChain types. The `OpenRouterLLMClient` is the only file importing `langchain_openai`.
- **`LLMClient.complete(*, messages, tools) -> AIMessage`** (the B1 port, unchanged). The real impl binds tools at construction; the `tools` arg is accepted for port-compatibility.
- **Meter every call**: extract `usage_metadata` + measured latency → a `StepRecord` and a `USAGE` event. **Retry transient 429/5xx with backoff (respect `Retry-After`); never re-route models** (the user chose the model; a retry uses the same one).
- **Think-before-act stays enforced** (the `reason` node already does this; do not weaken it).
- Prompts: author once as **decomposed Jinja2** (`{% include %}`); a `PromptResolver` allows runtime overrides. No prompt strings hardcoded in nodes.
- YAGNI: no real browser/funnel (B3), no persistent MEMORY.md (B4), no compaction yet (a later mini-plan). The browser stays the B1 `FakeBrowserSession`.
- Do **not** redefine wire/contract types; reuse `browser_agent_contracts`, B1 `AgentState`, `TOOL_SPECS`, `ToolDispatcher`, the nodes, `EventEmitter`, `StepRecord`.

### Shared spine (names every task must match)

```python
# events: add STREAM = "stream"; EventEmitter.emit_stream(token: str)
# app/prompt/loader.py: PromptLoader.render(name: str, ctx: dict) -> str   (jinja2 Environment, cached)
# app/prompt/resolver.py: PromptResolver(custom: dict|None); .render(name, ctx, loader) -> str
# app/prompts/agent/system.jinja2 includes identity/policy/context/tools/output-format partials
# app/agent/prompt.py: build_system_message(state, *, loader=None) -> SystemMessage   (now Jinja2-backed)
# app/llm/usage.py: UsageTracker.record(model_name, usage_metadata, latency_ms) -> StepRecord;
#                   .totals() -> dict;  async .emit(emitter, record) -> None
# app/llm/factory.py: build_chat_model(settings) -> Runnable  (ChatOpenAI(...).bind_tools(TOOL_SPECS, parallel_tool_calls=True))
# app/llm/openrouter.py: OpenRouterLLMClient(model, emitter, usage_tracker, *, max_retries=3, model_name="")
#                        async complete(*, messages, tools=None) -> AIMessage
# app/config/container.py: build_default_app(*, session, llm=None, sink=None) -> picks real LLM if key, else requires llm
```

## File Structure

```
backend/app/
├─ events/{protocol.py(+STREAM), emitter.py(+emit_stream)}
├─ prompt/{__init__.py, loader.py, resolver.py}
├─ prompts/agent/{system,identity,policy,context,tools,output-format}.jinja2
├─ agent/prompt.py            # build_system_message → Jinja2 loader (refactor)
├─ agent/graph.py             # InMemorySaver serde registration (B1 msgpack fix)
├─ llm/{usage.py, factory.py, openrouter.py}
├─ config/container.py        # config-gated real-vs-fake LLM
└─ agent/run.py               # real-LLM (fake browser) runner + __main__
backend/tests/
├─ agent/{test_events.py(+stream), test_prompt_loader.py, test_prompt_render.py}
├─ llm/{test_usage.py, test_openrouter_client.py, test_factory.py}
└─ agent/{test_container_b2.py, test_run_smoke.py}
```

---

### Task 1: STREAM event + `emit_stream`

**Files:** Modify `backend/app/events/protocol.py`, `backend/app/events/emitter.py`. Test: `backend/tests/agent/test_stream_event.py`

**Interfaces:** Produces `STREAM = "stream"` constant + `EventEmitter.emit_stream(token: str)` emitting `AgentEvent(event=STREAM, data={"token": token})`.

- [ ] **Step 1: Write the failing test `backend/tests/agent/test_stream_event.py`**

```python
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
```

- [ ] **Step 2: Run to verify it fails** — `cd backend && uv run pytest tests/agent/test_stream_event.py -v` → FAIL (`cannot import name 'STREAM'`).

- [ ] **Step 3: Add to `backend/app/events/protocol.py`** — add the constant near the others:

```python
STREAM = "stream"  # incremental LLM token
```

- [ ] **Step 4: Add to `backend/app/events/emitter.py`** — import `STREAM` in the existing import block, then add the method:

```python
    async def emit_stream(self, token: str) -> None:
        if token:
            await self._emit(STREAM, {"token": token})
```

- [ ] **Step 5: Run to verify it passes** — `cd backend && uv run pytest tests/agent/test_stream_event.py -v` → 2 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/events/protocol.py backend/app/events/emitter.py backend/tests/agent/test_stream_event.py
git commit -m "feat(events): STREAM event + EventEmitter.emit_stream"
```

---

### Task 2: PromptLoader + PromptResolver (Jinja2)

**Files:** Create `backend/app/prompt/__init__.py`, `backend/app/prompt/loader.py`, `backend/app/prompt/resolver.py`. Test: `backend/tests/agent/test_prompt_loader.py`

**Interfaces:** Produces `PromptLoader(templates_dir: Path | None = None)` with `render(name: str, ctx: dict) -> str` (cached Jinja2 `Environment(trim_blocks=True, lstrip_blocks=True)`, `FileSystemLoader` rooted at `app/prompts/`, supports `{% include %}`); `PromptResolver(custom: dict[str,str] | None)` with `render(name, ctx, loader) -> str` (renders a custom inline template string if present for `name`, else delegates to `loader.render`).

- [ ] **Step 1: Write the failing test `backend/tests/agent/test_prompt_loader.py`**

```python
from pathlib import Path
from app.prompt.loader import PromptLoader
from app.prompt.resolver import PromptResolver


def test_loader_renders_template_with_includes(tmp_path: Path):
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "part.jinja2").write_text("PART:{{ x }}")
    (tmp_path / "agent" / "main.jinja2").write_text("MAIN {% include 'agent/part.jinja2' %}")
    out = PromptLoader(templates_dir=tmp_path).render("agent/main.jinja2", {"x": "Y"})
    assert out == "MAIN PART:Y"


def test_resolver_prefers_custom_then_falls_back(tmp_path: Path):
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "sys.jinja2").write_text("FILE {{ x }}")
    loader = PromptLoader(templates_dir=tmp_path)
    r = PromptResolver({"agent_system": "CUSTOM {{ x }}"})
    assert r.render("agent_system", {"x": "1"}, loader, fallback="agent/sys.jinja2") == "CUSTOM 1"
    r2 = PromptResolver(None)
    assert r2.render("agent_system", {"x": "1"}, loader, fallback="agent/sys.jinja2") == "FILE 1"
```

- [ ] **Step 2: Run to verify it fails** — `cd backend && uv run pytest tests/agent/test_prompt_loader.py -v` → FAIL (`No module named 'app.prompt.loader'`).

- [ ] **Step 3: Create `backend/app/prompt/__init__.py`** (empty file).

- [ ] **Step 4: Create `backend/app/prompt/loader.py`**

```python
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_DEFAULT_DIR = Path(__file__).resolve().parent.parent / "prompts"


class PromptLoader:
    """Renders Jinja2 prompt templates (supports {% include %}) from app/prompts/."""

    def __init__(self, templates_dir: Path | None = None) -> None:
        self._dir = templates_dir or _DEFAULT_DIR
        self._env = Environment(
            loader=FileSystemLoader(str(self._dir)),
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=False,
            autoescape=select_autoescape(enabled_extensions=()),
        )

    def render(self, name: str, ctx: dict) -> str:
        return self._env.get_template(name).render(**ctx)

    def render_string(self, template: str, ctx: dict) -> str:
        return self._env.from_string(template).render(**ctx)


@lru_cache
def default_loader() -> PromptLoader:
    return PromptLoader()
```

- [ ] **Step 5: Create `backend/app/prompt/resolver.py`**

```python
from __future__ import annotations

from app.prompt.loader import PromptLoader


class PromptResolver:
    """Renders a runtime-custom template string per key, else falls back to a file."""

    def __init__(self, custom: dict[str, str] | None = None) -> None:
        self._custom = dict(custom or {})

    def render(self, key: str, ctx: dict, loader: PromptLoader, *, fallback: str) -> str:
        if key in self._custom:
            return loader.render_string(self._custom[key], ctx)
        return loader.render(fallback, ctx)
```

- [ ] **Step 6: Run to verify it passes** — `cd backend && uv run pytest tests/agent/test_prompt_loader.py -v` → 2 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/prompt backend/tests/agent/test_prompt_loader.py
git commit -m "feat(prompt): Jinja2 PromptLoader + PromptResolver"
```

---

### Task 3: Decomposed prompt templates + Jinja2-backed system message

**Files:** Create `backend/app/prompts/agent/{system,identity,policy,context,tools,output-format}.jinja2`. Modify `backend/app/agent/prompt.py`. Test: `backend/tests/agent/test_prompt_render.py`

**Interfaces:** Produces the decomposed templates; refactors `build_system_message(state, *, loader=None, resolver=None) -> SystemMessage` to render `agent/system.jinja2` with context `{tool_descriptions, memory, task}`. The B1 `SYSTEM_PROMPT` string is removed; the rendered prompt must still contain the tool list + memory + a think-before-act instruction so the existing `reason` tests pass.

- [ ] **Step 1: Write the failing test `backend/tests/agent/test_prompt_render.py`**

```python
from app.agent.state import AgentState
from app.agent.prompt import build_system_message


def test_system_message_contains_tools_memory_and_reasoning_rule():
    state = AgentState(task="log in", thread_id="t1", agent_memory={"url": "/auth"})
    msg = build_system_message(state)
    text = msg.content
    assert "Click(index)" in text            # tool descriptions rendered
    assert "url: /auth" in text               # memory block rendered
    assert "reason" in text.lower() and "tool" in text.lower()  # think-before-act guidance
    assert "log in" in text                   # task rendered
```

- [ ] **Step 2: Run to verify it fails** — `cd backend && uv run pytest tests/agent/test_prompt_render.py -v` → FAIL (template not found / assertion).

- [ ] **Step 3: Create the partials.** `backend/app/prompts/agent/identity.jinja2`:

```jinja2
You are a web browser agent. You complete the user's task by perceiving the page and acting on it.
```

`backend/app/prompts/agent/policy.jinja2`:

```jinja2
Operating rules:
- Each turn you receive the current page as a numbered list of interactable elements ([N] role "name").
- Think step by step in plain text FIRST (your reasoning), THEN call exactly one tool to act.
- Refer to elements only by their [N] index from the CURRENT list — indices change every turn.
- When the task is achieved (or proven impossible), call Complete(success, reason).
```

`backend/app/prompts/agent/context.jinja2`:

```jinja2
Task: {{ task }}

Working memory:
{{ memory }}
```

`backend/app/prompts/agent/tools.jinja2`:

```jinja2
Available tools:
{{ tool_descriptions }}
```

`backend/app/prompts/agent/output-format.jinja2`:

```jinja2
Respond with your reasoning as plain text, then a single tool call. Never emit a tool call with empty reasoning.
```

`backend/app/prompts/agent/system.jinja2`:

```jinja2
{% include 'agent/identity.jinja2' %}

{% include 'agent/policy.jinja2' %}

{% include 'agent/context.jinja2' %}

{% include 'agent/tools.jinja2' %}

{% include 'agent/output-format.jinja2' %}
```

- [ ] **Step 4: Replace `backend/app/agent/prompt.py`** entirely with the Jinja2-backed version:

```python
from __future__ import annotations

from langchain_core.messages import SystemMessage

from app.agent.state import AgentState
from app.prompt.loader import PromptLoader, default_loader
from app.prompt.resolver import PromptResolver
from app.tools.specs import tool_descriptions

_SYSTEM_TEMPLATE = "agent/system.jinja2"


def build_system_message(
    state: AgentState,
    *,
    loader: PromptLoader | None = None,
    resolver: PromptResolver | None = None,
) -> SystemMessage:
    loader = loader or default_loader()
    memory = "\n".join(f"- {k}: {v}" for k, v in state.agent_memory.items()) or "(empty)"
    ctx = {"tool_descriptions": tool_descriptions(), "memory": memory, "task": state.task}
    if resolver is not None:
        text = resolver.render("agent_system", ctx, loader, fallback=_SYSTEM_TEMPLATE)
    else:
        text = loader.render(_SYSTEM_TEMPLATE, ctx)
    return SystemMessage(content=text)
```

- [ ] **Step 5: Run to verify it passes** — `cd backend && uv run pytest tests/agent/test_prompt_render.py tests/agent/test_reason_node.py -v` → all passed (the reason-node tests still pass against the new prompt).

- [ ] **Step 6: Commit**

```bash
git add backend/app/prompts backend/app/agent/prompt.py backend/tests/agent/test_prompt_render.py
git commit -m "feat(prompt): decomposed Jinja2 system prompt; reason node renders via loader"
```

---

### Task 4: UsageTracker

**Files:** Create `backend/app/llm/usage.py`. Test: `backend/tests/llm/__init__.py`, `backend/tests/llm/test_usage.py`

**Interfaces:** Produces `UsageTracker()` with `record(model_name: str, usage_metadata: dict | None, latency_ms: float) -> StepRecord` (returns a `StepRecord(node="llm", input_tokens, output_tokens, latency_ms)` and accumulates totals), `totals() -> dict` (`{input_tokens, output_tokens, calls}`), and `async emit(emitter, record) -> None` (emits a `USAGE` event with the per-call numbers).

- [ ] **Step 1: Write the failing test `backend/tests/llm/test_usage.py`** (create `backend/tests/llm/__init__.py` empty first)

```python
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
```

- [ ] **Step 2: Run to verify it fails** — `cd backend && uv run pytest tests/llm/test_usage.py -v` → FAIL (`No module named 'app.llm.usage'`). (If collection errors, ensure `backend/tests/llm/__init__.py` exists.)

- [ ] **Step 3: Add `USAGE` to `backend/app/events/protocol.py`** if not already present (B1 defined it):

```python
USAGE = "usage"  # per-call token/cost usage (define only if missing)
```
*(B1 already defines `USAGE`; if it exists, skip this step.)*

- [ ] **Step 4: Create `backend/app/llm/usage.py`**

```python
from __future__ import annotations

from app.events.emitter import EventEmitter
from app.events.protocol import USAGE
from app.telemetry.records import StepRecord


class UsageTracker:
    """Accumulates per-call LLM usage and renders StepRecords + USAGE events."""

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.calls = 0
        self._last_model = ""

    def record(self, model_name: str, usage_metadata: dict | None, latency_ms: float) -> StepRecord:
        u = usage_metadata or {}
        inp = int(u.get("input_tokens", 0))
        out = int(u.get("output_tokens", 0))
        self.input_tokens += inp
        self.output_tokens += out
        self.calls += 1
        self._last_model = model_name
        return StepRecord(step=0, node="llm", input_tokens=inp, output_tokens=out, latency_ms=latency_ms)

    def totals(self) -> dict:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens, "calls": self.calls}

    async def emit(self, emitter: EventEmitter, record: StepRecord) -> None:
        await emitter._emit(  # noqa: SLF001 — intentional internal dispatch
            USAGE,
            {
                "model": self._last_model,
                "inputTokens": record.input_tokens,
                "outputTokens": record.output_tokens,
                "latencyMs": record.latency_ms,
            },
        )
```

- [ ] **Step 5: Run to verify it passes** — `cd backend && uv run pytest tests/llm/test_usage.py -v` → 3 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/llm/usage.py backend/tests/llm
git commit -m "feat(llm): UsageTracker (per-call metering + USAGE event)"
```

---

### Task 5: OpenRouter LLMClient (streaming + retry)

**Files:** Create `backend/app/llm/openrouter.py`. Test: `backend/tests/llm/test_openrouter_client.py`

**Interfaces:** Produces `OpenRouterLLMClient(model, emitter, usage_tracker, *, max_retries=3, model_name="")` satisfying `LLMClient`. `complete()` `astream`s the injected `model` (a `bind_tools`'d Runnable), accumulates chunks into one message (`full = chunk if full is None else full + chunk`), emits each chunk's text via `emitter.emit_stream`, records usage, and returns an `AIMessage` built from the accumulated `content`/`tool_calls`/`usage_metadata`. Transient errors (a status code in {429,500,502,503,504} on the exception, or `RateLimitError`-like) retry with capped exponential backoff; the model is never swapped.

- [ ] **Step 1: Write the failing test `backend/tests/llm/test_openrouter_client.py`**

```python
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
```

- [ ] **Step 2: Run to verify it fails** — `cd backend && uv run pytest tests/llm/test_openrouter_client.py -v` → FAIL (`No module named 'app.llm.openrouter'`).

- [ ] **Step 3: Create `backend/app/llm/openrouter.py`**

```python
from __future__ import annotations

import asyncio
import time
from typing import Sequence

from langchain_core.messages import AIMessage, BaseMessage
from pydantic import BaseModel

from app.events.emitter import EventEmitter
from app.llm.usage import UsageTracker

_TRANSIENT_STATUS = {429, 500, 502, 503, 504}


def _status_of(exc: Exception) -> int | None:
    for attr in ("status_code", "http_status", "code"):
        v = getattr(exc, attr, None)
        if isinstance(v, int):
            return v
    resp = getattr(exc, "response", None)
    return getattr(resp, "status_code", None) if resp is not None else None


def _is_transient(exc: Exception) -> bool:
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
                       tools: Sequence[type[BaseModel]] | None = None) -> AIMessage:
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
```

- [ ] **Step 4: Run to verify it passes** — `cd backend && uv run pytest tests/llm/test_openrouter_client.py -v` → 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/llm/openrouter.py backend/tests/llm/test_openrouter_client.py
git commit -m "feat(llm): OpenRouterLLMClient (streaming + metering + transient retry)"
```

---

### Task 6: LLM factory + config-gated container wiring

**Files:** Create `backend/app/llm/factory.py`. Modify `backend/app/config/container.py`, `backend/app/config/settings.py`. Test: `backend/tests/llm/test_factory.py`, `backend/tests/agent/test_container_b2.py`

**Interfaces:** Produces `build_chat_model(settings) -> Runnable` (`ChatOpenAI(...).bind_tools(TOOL_SPECS, parallel_tool_calls=True)`); `build_default_app(*, session, llm=None, sink=None)` now builds a real `OpenRouterLLMClient` when `settings.openrouter_api_key` is set and no explicit `llm` is passed, else uses the injected `llm` (raising if neither). Adds `llm_temperature: float = 0.2` and `llm_max_retries: int = 3` to settings.

- [ ] **Step 1: Write the failing test `backend/tests/llm/test_factory.py`**

```python
from app.llm.factory import build_chat_model
from app.config.settings import Settings


def test_build_chat_model_binds_tools_and_targets_openrouter():
    s = Settings(openrouter_api_key="sk-test", agent_model="anthropic/claude-sonnet-4.6")
    model = build_chat_model(s)
    # bind_tools returns a RunnableBinding; the bound kwargs carry our tool schemas
    assert hasattr(model, "astream")
    bound = getattr(model, "kwargs", {})
    names = {t["function"]["name"] for t in bound.get("tools", [])} if bound.get("tools") else set()
    assert {"Click", "Complete"} <= names
```

- [ ] **Step 2: Write the failing test `backend/tests/agent/test_container_b2.py`**

```python
import pytest
from app.config.container import build_default_app
from app.config.settings import Settings
from tests.fakes.fake_browser import FakeBrowserSession
from tests.fakes.fake_llm import FakeLLMClient


def test_container_uses_injected_fake_when_no_key(monkeypatch):
    from app.config import container
    monkeypatch.setattr(container, "get_settings", lambda: Settings(openrouter_api_key=""))
    graph, *_ = build_default_app(session=FakeBrowserSession(), llm=FakeLLMClient(turns=[]))
    assert graph is not None


def test_container_requires_an_llm_when_no_key(monkeypatch):
    from app.config import container
    monkeypatch.setattr(container, "get_settings", lambda: Settings(openrouter_api_key=""))
    with pytest.raises(ValueError):
        build_default_app(session=FakeBrowserSession(), llm=None)
```

- [ ] **Step 3: Run to verify they fail** — `cd backend && uv run pytest tests/llm/test_factory.py tests/agent/test_container_b2.py -v` → FAIL.

- [ ] **Step 4: Add settings fields** — in `backend/app/config/settings.py`, inside `Settings` (after `max_steps`):

```python
    llm_temperature: float = 0.2
    llm_max_retries: int = 3
```

- [ ] **Step 5: Create `backend/app/llm/factory.py`**

```python
from __future__ import annotations

from app.config.settings import Settings
from app.tools.specs import TOOL_SPECS


def build_chat_model(settings: Settings):
    """A bind_tools'd ChatOpenAI Runnable pointed at OpenRouter."""
    from langchain_openai import ChatOpenAI

    model = ChatOpenAI(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        model=settings.agent_model,
        temperature=settings.llm_temperature,
        stream_usage=True,
        max_retries=0,  # OpenRouterLLMClient owns retries
    )
    return model.bind_tools(TOOL_SPECS, parallel_tool_calls=True)
```

- [ ] **Step 6: Replace `backend/app/config/container.py`**

```python
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
```

- [ ] **Step 7: Run to verify they pass** — `cd backend && uv run pytest tests/llm/test_factory.py tests/agent/test_container_b2.py -v` → all passed. (If the factory test's `kwargs`/`tools` shape differs across langchain versions, assert instead that `build_chat_model(s)` returns an object with `astream` and that `TOOL_SPECS` names are present in `model.tools` or `model.kwargs["tools"]` — keep the assertion on the OpenAI function-schema names `Click`/`Complete`.)

- [ ] **Step 8: Commit**

```bash
git add backend/app/llm/factory.py backend/app/config/container.py backend/app/config/settings.py backend/tests/llm/test_factory.py backend/tests/agent/test_container_b2.py
git commit -m "feat(llm): chat-model factory + config-gated real/fake LLM in the container"
```

---

### Task 7: Checkpointer serde registration (B1 msgpack fix)

**Files:** Modify `backend/app/agent/graph.py`. Test: `backend/tests/agent/test_checkpoint_serde.py`

**Interfaces:** The compiled graph's `InMemorySaver` is constructed with a serde that registers our Pydantic state/contract types so checkpoint round-trips don't log "Deserializing unregistered type … will be blocked in a future version".

- [ ] **Step 1: Write the failing test `backend/tests/agent/test_checkpoint_serde.py`**

```python
import warnings
from app.config.container import build_default_app
from app.agent.demo import run
from tests.fakes.fake_browser import FakeBrowserSession
from tests.fakes.fake_llm import FakeLLMClient, ai


async def test_no_unregistered_type_warning_on_checkpoint_roundtrip(capsys):
    llm = FakeLLMClient(turns=[ai("done", [{"name": "Complete", "args": {"success": True, "reason": "ok"}, "id": "1"}])])
    graph, *_ = build_default_app(session=FakeBrowserSession(), llm=llm)
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any Python warning becomes an error
        final = await run(graph, task="t", thread_id="t1")
    assert final.status == "done"
    out = capsys.readouterr()
    assert "Deserializing unregistered type" not in (out.out + out.err)
```

- [ ] **Step 2: Run to verify it fails** — `cd backend && uv run pytest tests/agent/test_checkpoint_serde.py -v` → FAIL (the "Deserializing unregistered type" log appears in captured output).

- [ ] **Step 3: Update `backend/app/agent/graph.py`** — register the modules with the checkpointer serde. Replace the `compile(...)` call and add the serde import + builder near the top:

```python
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

_ALLOWED_MSGPACK_MODULES = (
    "browser_agent_contracts.models",
    "app.telemetry.records",
    "app.agent.state",
)


def _checkpointer() -> InMemorySaver:
    return InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_MSGPACK_MODULES))
```

Then change the final line of `build_graph` from `return g.compile(checkpointer=InMemorySaver())` to:

```python
    return g.compile(checkpointer=_checkpointer())
```

*(If `JsonPlusSerializer.__init__` does not accept `allowed_msgpack_modules` in the installed langgraph version, instead set the env var at import time: `os.environ.setdefault("LANGGRAPH_ALLOWED_MSGPACK_MODULES", ",".join(_ALLOWED_MSGPACK_MODULES))` — confirm which the installed version supports by checking the warning text, which names the exact mechanism, and use that one. Keep the test as the gate.)*

- [ ] **Step 4: Run to verify it passes** — `cd backend && uv run pytest tests/agent/test_checkpoint_serde.py -v` → 1 passed (no warning, status done).

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/graph.py backend/tests/agent/test_checkpoint_serde.py
git commit -m "fix(agent): register state/contract types with checkpointer serde (no msgpack warnings)"
```

---

### Task 8: Live runner + smoke test + full-suite gate

**Files:** Create `backend/app/agent/run.py`, `backend/tests/agent/test_run_smoke.py`. Test: as below.

**Interfaces:** Produces `app/agent/run.py` with `async def run_task(task: str, *, thread_id="live") -> AgentState` that builds the real app from settings (real LLM + `FakeBrowserSession` for B2) and `astream`s it, plus a `__main__`. A smoke test runs the real OpenRouter path **only when `OPENROUTER_API_KEY` is set** (else skipped), keeping CI hermetic.

- [ ] **Step 1: Write `backend/tests/agent/test_run_smoke.py`**

```python
import os
import pytest
from app.agent.run import run_task


@pytest.mark.skipif(not os.getenv("OPENROUTER_API_KEY"), reason="needs a real OpenRouter key")
async def test_live_smoke_reaches_terminal_status():
    final = await run_task("Say the task is done by calling Complete(success=true).", thread_id="smoke")
    assert final.status in {"done", "failed"}
    assert final.step >= 1
```

- [ ] **Step 2: Run to verify it is collected + skipped** — `cd backend && uv run pytest tests/agent/test_run_smoke.py -v` → FAIL (`No module named 'app.agent.run'`).

- [ ] **Step 3: Create `backend/app/agent/run.py`**

```python
from __future__ import annotations

import asyncio

from app.agent.demo import run
from app.agent.state import AgentState
from app.config.container import build_default_app
from tests.fakes.fake_browser import FakeBrowserSession


async def run_task(task: str, *, thread_id: str = "live") -> AgentState:
    """Run the agent with the REAL OpenRouter LLM against a fake browser (B2)."""
    graph, emitter, store, sink = build_default_app(session=FakeBrowserSession())
    return await run(graph, task=task, thread_id=thread_id)


async def _main() -> None:
    final = await run_task("Decide there's nothing to do and call Complete(success=true, reason='noop').")
    print(f"status={final.status} success={final.success} reason={final.reason!r} steps={final.step}")


if __name__ == "__main__":
    asyncio.run(_main())
```

- [ ] **Step 4: Run to verify it passes/skips** — `cd backend && uv run pytest tests/agent/test_run_smoke.py -v` → 1 skipped (no key in this shell) OR 1 passed (if a key is exported). Either is green.

- [ ] **Step 5: Optional live check (only if you have a key in `.env`)** — `cd backend && uv run python -m app.agent.run` → prints `status=done` (or `failed`) with `steps>=1`, streaming real tokens. *(This spends a small amount of OpenRouter credit.)*

- [ ] **Step 6: Full backend suite (no regressions)** — `cd backend && uv run pytest -q` → all pass (B1 33 + B2 new), pristine.

- [ ] **Step 7: Commit**

```bash
git add backend/app/agent/run.py backend/tests/agent/test_run_smoke.py
git commit -m "feat(agent): real-LLM runner + gated live smoke test"
```

---

## Self-Review

**Spec coverage (design spec §7.3 prompts, §7.5 LLM/metering/streaming):**
- Real OpenRouter `LLMClient` via `ChatOpenAI`(base_url) behind the port → Tasks 5, 6. ✓
- `bind_tools(..., parallel_tool_calls=True)`; graph/services never see LangChain (only `openrouter.py`/`factory.py` import it) → Tasks 5, 6. ✓
- Token streaming → emitter (`STREAM`) → Tasks 1, 5. ✓
- Meter every call (tokens + latency) → `StepRecord` + `USAGE` event → Tasks 4, 5. ✓
- Retry transient 429/5xx with backoff (respect `Retry-After`), never re-route → Task 5. ✓
- Decomposed Jinja2 prompts + `PromptLoader`/`PromptResolver`; reason node renders via loader → Tasks 2, 3. ✓
- Keys server-side only (settings/.env, never in events/logs) → Tasks 5, 6 (emitter carries tokens/usage, never the key). ✓
- B1 msgpack checkpointer warning fixed → Task 7. ✓
- **Out of scope (correctly deferred):** real browser/funnel (B3); persistent MEMORY.md (B4); compaction (later mini-plan). Browser stays the B1 fake.

**Placeholder scan:** No "TBD/handle errors". The two version-sensitive spots (Task 6 `tools` introspection, Task 7 serde mechanism) carry explicit fallbacks gated by a test, not vague hand-waving. ✓

**Type consistency:** `OpenRouterLLMClient(model, emitter, usage_tracker, *, max_retries, model_name)`, `UsageTracker.record(model_name, usage_metadata, latency_ms)->StepRecord`, `build_chat_model(settings)`, `build_system_message(state, *, loader, resolver)`, `STREAM`/`USAGE` constants, and the `build_default_app(*, session, llm=None, sink=None)` signature are consistent across Tasks 1–8 and match the B1 `LLMClient`/`AgentState`/`EventEmitter`/`StepRecord` surfaces. ✓

**Note for the implementer:** the LLM port stays `complete(*, messages, tools)`; the real client binds tools at construction and ignores the per-call `tools` arg (kept for parity with the fake). The `reason` node already passes `tools=TOOL_SPECS` to both — no node change needed for tool binding.
