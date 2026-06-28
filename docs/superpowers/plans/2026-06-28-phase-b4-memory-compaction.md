# Phase B4 — Persistent MEMORY.md + Context Compaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the agent durable, file-backed memory (`MEMORY.md`, written async/non-blocking) and bound the LLM context so long runs stop ballooning to 100k+ tokens.

**Architecture:** Two complementary subsystems. **(A) Memory:** a `MemoryStore` port + `AsyncMarkdownMemory` impl (an `asyncio.Queue` + background worker writing `runs/{thread_id}/memory.md` via `aiofiles`); the `act` node enqueues a write whenever `agent_memory` changes, `finalize` appends a run summary, and a run rehydrates `agent_memory` from the file on resume. **(B) Compaction:** a pure `compact_for_llm()` applied in the `reason` node before each LLM call — it drops *superseded* observation messages (old observations have stale element indices the architecture forbids reusing) and truncates old tool outputs, keeping only the freshest observation + the full action trail. The two halves divide labor: compaction discards *ephemeral* page snapshots; `MEMORY.md` persists the *durable* facts the agent chose to remember.

**Tech Stack:** Python 3.12, asyncio, `aiofiles`, Pydantic v2, LangGraph, LangChain core messages (`HumanMessage`/`AIMessage`/`ToolMessage`), pytest (`asyncio_mode=auto`).

## Global Constraints

- **Async writer is non-blocking:** `append()` uses `Queue.put_nowait()`; on a full queue it **drops the write and logs a warning** — it never blocks the agent loop or raises into it. (spec §7.2)
- **Worker never crashes the loop:** the background drain task catches per-item exceptions, logs them, and keeps running. `start()` / `stop(timeout)` lifecycle; `stop` drains remaining items within the timeout then cancels. (spec §7.2)
- **MEMORY.md format:** one Markdown document with exactly two sections — `## Knowledge` (lines `- **key**: value`) and `## Run History` (newest-relevant entries). (spec §7.2, Decision 11)
- **Compaction Phase-B scope:** Layer 0 (drop superseded observations) + Layer 1 (truncate old tool outputs) only. **Layer 2 (LLM-summarize) is explicitly deferred** to a fast-follow — do NOT build it here. (spec §7.5, scope note line 50)
- **Compaction never breaks tool pairing:** never drop an `AIMessage` that carries `tool_calls` nor its matching `ToolMessage` (paired by `tool_call_id`). Only observation `HumanMessage`s are dropped; old tool outputs are *truncated in place*, not removed. (LangChain message-sequence rule)
- **Emit `context_status` every turn** with the compaction stats + the real `input_tokens` of the call just made, so token cost is observable. (spec §7.5)
- **SOLID/DI:** `MemoryStore` is a Protocol; `AsyncMarkdownMemory` is the only impl; it is constructed and started **only** in `app/config/container.py`. Nodes receive it injected — no node imports the concrete class. (CLAUDE.md §6)
- **Files land under a configurable base:** `runs/{thread_id}/memory.md`, base dir from `Settings.runs_dir` (default `"runs"`).
- TDD: red → green → commit per step. Do not run `git` commands if executing under subagent-driven-development — the controller commits.

---

## File Structure

**Track A — Memory (mostly independent of Track B):**
- `backend/app/memory/document.py` — pure Markdown document functions (no I/O).
- `backend/app/memory/store.py` — `MemoryStore` Protocol + `AsyncMarkdownMemory` impl (queue + worker + `aiofiles`).
- `backend/app/agent/nodes/act.py` — enqueue a memory write when `agent_memory` changes (modify).
- `backend/app/agent/graph.py` (finalize node) — `append_run` on finish (modify).
- `backend/app/agent/demo.py` (`run`) — rehydrate `agent_memory` from the store before the run (modify).
- `backend/app/config/{settings,container}.py` — `runs_dir` setting; construct/start/stop the store (modify).

**Track B — Compaction (mostly independent of Track A):**
- `backend/app/agent/compaction.py` — pure `compact_for_llm()` (no I/O, no LLM).
- `backend/app/agent/nodes/observe.py` — tag observation messages with `name="observation"` (modify).
- `backend/app/agent/nodes/reason.py` — apply compaction before the LLM call; emit `context_status` (modify).
- `backend/app/events/{protocol,emitter}.py` — `CONTEXT_STATUS` event + `emit_context_status` (modify).

**Tracks A and B touch disjoint files** (A: memory/, act, graph, demo, config; B: compaction, observe, reason, events) and can be implemented as parallel waves. Within each track, tasks are sequential.

---

## Track A — Persistent MEMORY.md

### Task 1: Markdown document functions (pure, no I/O)

**Files:**
- Create: `backend/app/memory/document.py`
- Test: `backend/tests/memory/test_document.py` (create `backend/tests/memory/__init__.py` if the package dir has none)

**Interfaces:**
- Produces:
  - `build_document(knowledge: dict[str, str], runs: list[str]) -> str`
  - `parse_knowledge(md: str) -> dict[str, str]`
  - `update_knowledge(md: str, key: str, value: str) -> str`
  - `append_run(md: str, run_summary: str, *, max_runs: int = 20) -> str`
- Document shape (exact):
  ```markdown
  # Agent Memory

  ## Knowledge
  - **invoice_url**: https://x/invoices
  - **logged_in**: true

  ## Run History
  - Signed in and downloaded March invoice (done)
  - Searched for the report but the link was missing (failed)
  ```

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/memory/test_document.py
from app.memory.document import build_document, parse_knowledge, update_knowledge, append_run


def test_build_then_parse_roundtrips_knowledge():
    md = build_document({"a": "1", "b": "two"}, ["did a thing (done)"])
    assert "## Knowledge" in md and "## Run History" in md
    assert "- **a**: 1" in md and "- **b**: two" in md
    assert "- did a thing (done)" in md
    assert parse_knowledge(md) == {"a": "1", "b": "two"}


def test_parse_knowledge_ignores_run_history_and_malformed_lines():
    md = build_document({"k": "v"}, ["run one (done)"])
    # a stray line in Run History must not leak into knowledge
    assert parse_knowledge(md) == {"k": "v"}


def test_update_knowledge_adds_and_overwrites_in_place():
    md = build_document({"a": "1"}, [])
    md = update_knowledge(md, "b", "2")        # add
    md = update_knowledge(md, "a", "99")       # overwrite
    assert parse_knowledge(md) == {"a": "99", "b": "2"}


def test_append_run_keeps_newest_and_caps_length():
    md = build_document({}, [])
    for i in range(25):
        md = append_run(md, f"run {i} (done)", max_runs=20)
    runs = [ln for ln in md.splitlines() if ln.startswith("- ") and "run " in ln]
    assert len(runs) == 20            # capped
    assert "run 24 (done)" in md      # newest kept
    assert "run 4 (done)" not in md   # oldest dropped
```

- [ ] **Step 2: Run tests, verify they fail** — `cd backend && uv run pytest tests/memory/test_document.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement `document.py`**

```python
# backend/app/memory/document.py
"""Pure functions for the agent's MEMORY.md document. No I/O, no LLM."""
from __future__ import annotations

import re

_KNOWLEDGE_RE = re.compile(r"^- \*\*(?P<key>.+?)\*\*: (?P<value>.*)$")


def build_document(knowledge: dict[str, str], runs: list[str]) -> str:
    lines = ["# Agent Memory", "", "## Knowledge"]
    lines += [f"- **{k}**: {v}" for k, v in knowledge.items()]
    lines += ["", "## Run History"]
    lines += [f"- {r}" for r in runs]
    return "\n".join(lines) + "\n"


def parse_knowledge(md: str) -> dict[str, str]:
    out: dict[str, str] = {}
    in_knowledge = False
    for line in md.splitlines():
        if line.strip() == "## Knowledge":
            in_knowledge = True
            continue
        if line.startswith("## ") and line.strip() != "## Knowledge":
            in_knowledge = False
            continue
        if in_knowledge:
            m = _KNOWLEDGE_RE.match(line)
            if m:
                out[m.group("key")] = m.group("value")
    return out


def _runs(md: str) -> list[str]:
    runs: list[str] = []
    in_runs = False
    for line in md.splitlines():
        if line.strip() == "## Run History":
            in_runs = True
            continue
        if line.startswith("## ") and line.strip() != "## Run History":
            in_runs = False
            continue
        if in_runs and line.startswith("- "):
            runs.append(line[2:])
    return runs


def update_knowledge(md: str, key: str, value: str) -> str:
    knowledge = parse_knowledge(md)
    knowledge[key] = value
    return build_document(knowledge, _runs(md))


def append_run(md: str, run_summary: str, *, max_runs: int = 20) -> str:
    runs = _runs(md)
    runs.append(run_summary)
    runs = runs[-max_runs:]
    return build_document(parse_knowledge(md), runs)
```

- [ ] **Step 4: Run tests, verify pass** — `cd backend && uv run pytest tests/memory/test_document.py -v` → PASS.
- [ ] **Step 5: Commit** — `feat(memory): MEMORY.md document functions (build/parse/update/append_run)`

---

### Task 2: `MemoryStore` port + `AsyncMarkdownMemory` (queue + worker + aiofiles)

**Files:**
- Create: `backend/app/memory/store.py`
- Test: `backend/tests/memory/test_async_markdown.py`
- Modify: `backend/pyproject.toml` (add `aiofiles` dependency)

**Interfaces:**
- Consumes: `app.memory.document` (`build_document`, `parse_knowledge`, `update_knowledge`, `append_run`).
- Produces:
  - `class MemoryStore(Protocol)` with: `async def start() -> None`, `async def stop(timeout: float = 2.0) -> None`, `def append(thread_id: str, key: str, value: str) -> None` (non-blocking, sync signature — enqueues), `def append_run(thread_id: str, summary: str) -> None` (non-blocking enqueue), `async def load(thread_id: str) -> dict[str, str]`.
  - `class AsyncMarkdownMemory` implementing it, constructed as `AsyncMarkdownMemory(base_dir: str = "runs", max_queue: int = 1000)`.

- [ ] **Step 1: Add dependency** — in `backend/pyproject.toml` add `"aiofiles>=23"` to `dependencies`, then `cd backend && uv sync`.

- [ ] **Step 2: Write failing tests**

```python
# backend/tests/memory/test_async_markdown.py
import asyncio
from pathlib import Path

from app.memory.store import AsyncMarkdownMemory


async def test_append_writes_knowledge_file(tmp_path):
    mem = AsyncMarkdownMemory(base_dir=str(tmp_path))
    await mem.start()
    try:
        mem.append("t1", "invoice_url", "https://x")
        mem.append("t1", "logged_in", "true")
        await asyncio.sleep(0.05)  # let the worker drain
    finally:
        await mem.stop()
    md = Path(tmp_path, "t1", "memory.md").read_text()
    assert "- **invoice_url**: https://x" in md and "- **logged_in**: true" in md


async def test_load_roundtrips_after_stop(tmp_path):
    mem = AsyncMarkdownMemory(base_dir=str(tmp_path))
    await mem.start()
    mem.append("t2", "k", "v")
    await mem.stop()                      # stop drains remaining writes
    mem2 = AsyncMarkdownMemory(base_dir=str(tmp_path))
    assert await mem2.load("t2") == {"k": "v"}   # load needs no running worker


async def test_append_run_persists_summary(tmp_path):
    mem = AsyncMarkdownMemory(base_dir=str(tmp_path))
    await mem.start()
    mem.append_run("t3", "did the task (done)")
    await mem.stop()
    md = Path(tmp_path, "t3", "memory.md").read_text()
    assert "- did the task (done)" in md


async def test_append_after_queue_full_drops_not_raises(tmp_path, caplog):
    mem = AsyncMarkdownMemory(base_dir=str(tmp_path), max_queue=1)
    # do NOT start the worker, so nothing drains; fill the queue past capacity
    mem.append("t4", "a", "1")
    mem.append("t4", "b", "2")   # queue full -> must drop + warn, never raise
    assert any("drop" in r.message.lower() or "full" in r.message.lower() for r in caplog.records)
```

- [ ] **Step 3: Run tests, verify they fail** — `cd backend && uv run pytest tests/memory/test_async_markdown.py -v` → FAIL (module missing).

- [ ] **Step 4: Implement `store.py`**

```python
# backend/app/memory/store.py
"""MemoryStore port + AsyncMarkdownMemory: non-blocking enqueue, background aiofiles writer."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Protocol

import aiofiles

from app.memory.document import append_run, build_document, parse_knowledge, update_knowledge

logger = logging.getLogger(__name__)


class MemoryStore(Protocol):
    async def start(self) -> None: ...
    async def stop(self, timeout: float = 2.0) -> None: ...
    def append(self, thread_id: str, key: str, value: str) -> None: ...
    def append_run(self, thread_id: str, summary: str) -> None: ...
    async def load(self, thread_id: str) -> dict[str, str]: ...


class AsyncMarkdownMemory:
    """Writes runs/{thread_id}/memory.md off the hot path via an asyncio.Queue + worker."""

    def __init__(self, base_dir: str = "runs", max_queue: int = 1000) -> None:
        self._base = Path(base_dir)
        self._queue: asyncio.Queue[tuple[str, str, str, str]] = asyncio.Queue(maxsize=max_queue)
        self._worker: asyncio.Task | None = None

    def _path(self, thread_id: str) -> Path:
        return self._base / thread_id / "memory.md"

    # --- non-blocking producers (sync signatures; enqueue only) ---
    def append(self, thread_id: str, key: str, value: str) -> None:
        self._enqueue(("knowledge", thread_id, key, value))

    def append_run(self, thread_id: str, summary: str) -> None:
        self._enqueue(("run", thread_id, summary, ""))

    def _enqueue(self, item: tuple[str, str, str, str]) -> None:
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            logger.warning("memory queue full — dropping write %s/%s", item[0], item[1])

    # --- lifecycle ---
    async def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._run())

    async def stop(self, timeout: float = 2.0) -> None:
        if self._worker is None:
            return
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("memory queue did not drain within %.1fs", timeout)
        self._worker.cancel()
        try:
            await self._worker
        except asyncio.CancelledError:
            pass
        self._worker = None

    # --- worker ---
    async def _run(self) -> None:
        while True:
            kind, thread_id, a, b = await self._queue.get()
            try:
                await self._apply(kind, thread_id, a, b)
            except Exception:  # never let one bad write kill the worker
                logger.exception("memory write failed for %s", thread_id)
            finally:
                self._queue.task_done()

    async def _apply(self, kind: str, thread_id: str, a: str, b: str) -> None:
        path = self._path(thread_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        md = path.read_text() if path.exists() else build_document({}, [])
        md = update_knowledge(md, a, b) if kind == "knowledge" else append_run(md, a)
        async with aiofiles.open(path, "w") as f:
            await f.write(md)

    async def load(self, thread_id: str) -> dict[str, str]:
        path = self._path(thread_id)
        if not path.exists():
            return {}
        async with aiofiles.open(path, "r") as f:
            return parse_knowledge(await f.read())
```

- [ ] **Step 5: Run tests, verify pass** — `cd backend && uv run pytest tests/memory/test_async_markdown.py -v` → PASS. (`test_append_after_queue_full_drops_not_raises` proves non-blocking drop; `maxsize=1` holds the first item, the second overflows.)
- [ ] **Step 6: Commit** — `feat(memory): AsyncMarkdownMemory store — non-blocking queue + aiofiles worker`

---

### Task 3: Wire memory into the agent (enqueue / append_run / rehydrate / lifecycle)

**Files:**
- Modify: `backend/app/agent/nodes/act.py` (enqueue a write when `agent_memory` changes)
- Modify: `backend/app/agent/graph.py` (finalize node calls `append_run`)
- Modify: `backend/app/agent/demo.py` (`run` rehydrates `agent_memory` before streaming)
- Modify: `backend/app/config/settings.py` (`runs_dir`) and `backend/app/config/container.py` (construct + return the store; start/stop lifecycle)
- Test: `backend/tests/agent/test_memory_wiring.py`

**Interfaces:**
- Consumes: `AsyncMarkdownMemory` (Task 2). The `act` node and `finalize` node receive a `memory: MemoryStore` injected (same closure-injection pattern the nodes already use for `session`/`emitter`/`store`).
- `build_default_app(...)` currently returns `(graph, emitter, store, sink)`. **Change it to also return the memory store: `(graph, emitter, store, sink, memory)`** — update all call sites (the demos, any tests that unpack it).
- Produces: after a `Remember` tool call, `memory.append(thread_id, key, value)` is enqueued; at finalize, `memory.append_run(thread_id, summary)`; `run()` seeds `agent_memory` from `memory.load(thread_id)`.

- [ ] **Step 1: Write failing test** (uses a fake store to assert the wiring, no files needed)

```python
# backend/tests/agent/test_memory_wiring.py
from app.agent.demo import run
from app.config.container import build_default_app
from tests.fakes.fake_browser import FakeBrowserSession
from tests.fakes.fake_llm import FakeLLMClient, ai


class FakeMemory:
    def __init__(self, preload=None):
        self.appends = []
        self.runs = []
        self._preload = preload or {}
        self.started = self.stopped = False
    async def start(self): self.started = True
    async def stop(self, timeout: float = 2.0): self.stopped = True
    def append(self, thread_id, key, value): self.appends.append((thread_id, key, value))
    def append_run(self, thread_id, summary): self.runs.append((thread_id, summary))
    async def load(self, thread_id): return dict(self._preload)


async def test_remember_enqueues_write_and_finalize_appends_run():
    llm = FakeLLMClient(turns=[
        ai("note it", [{"name": "Remember", "args": {"key": "url", "value": "https://x"}, "id": "r1"}]),
        ai("done", [{"name": "Complete", "args": {"success": True, "reason": "all set"}, "id": "c1"}]),
    ])
    mem = FakeMemory()
    graph, emitter, store, sink, _ = build_default_app(session=FakeBrowserSession(), llm=llm, memory=mem)
    final = await run(graph, task="t", thread_id="tw", memory=mem)
    assert final.status == "done"
    assert ("tw", "url", "https://x") in mem.appends     # Remember enqueued a write
    assert mem.runs and mem.runs[0][0] == "tw"           # finalize appended a run summary


async def test_run_rehydrates_agent_memory_from_store():
    llm = FakeLLMClient(turns=[
        ai("done", [{"name": "Complete", "args": {"success": True, "reason": "ok"}, "id": "c1"}]),
    ])
    mem = FakeMemory(preload={"prior": "fact"})
    graph, emitter, store, sink, _ = build_default_app(session=FakeBrowserSession(), llm=llm, memory=mem)
    final = await run(graph, task="t", thread_id="tw2", memory=mem)
    assert final.agent_memory.get("prior") == "fact"   # loaded from MEMORY.md before the run
```

- [ ] **Step 2: Run test, verify it fails** — `cd backend && uv run pytest tests/agent/test_memory_wiring.py -v` → FAIL (`build_default_app` doesn't accept/return `memory`; `run` has no `memory` kwarg).

- [ ] **Step 3: Implement the wiring.**

  **3a. `settings.py`** — add field: `runs_dir: str = "runs"`.

  **3b. `container.py`** — accept an optional `memory` and construct a default; return it:
  ```python
  # in build_default_app(..., memory: MemoryStore | None = None):
  if memory is None:
      from app.memory.store import AsyncMarkdownMemory
      memory = AsyncMarkdownMemory(base_dir=settings.runs_dir)
  # inject `memory` into the act + finalize node builders (same way session/emitter/store are injected)
  # return (graph, emitter, store, sink, memory)
  ```
  (Do NOT call `await memory.start()` inside `build_default_app` — it's sync. Start/stop is the run's job; see 3d. If `build_default_app` is async in this codebase, start it here and stop in `run`’s finally — match the existing pattern; the tests above call `run`, which must guarantee start before streaming and stop after.)

  **3c. `act.py`** — the node already computes `memory` dict updates and detects `if memory != state.agent_memory`. Inside that branch, for each newly-added/changed key enqueue a write:
  ```python
  for k, v in merged_memory.items():
      if state.agent_memory.get(k) != v:
          memory.append(state.thread_id, k, v)
  ```
  (`memory` is the injected store; `merged_memory` is the dict the node already builds.)

  **3d. `graph.py` finalize node** — after status is decided, enqueue a run summary:
  ```python
  memory.append_run(state.thread_id, f"{state.reason} ({state.status})")
  ```

  **3e. `demo.py` `run`** — add `memory: MemoryStore | None = None`; rehydrate + manage lifecycle:
  ```python
  async def run(graph, task, thread_id="demo", *, answer_provider=None, emitter=None, memory=None):
      config = {"configurable": {"thread_id": thread_id}}
      preload = await memory.load(thread_id) if memory is not None else {}
      if memory is not None:
          await memory.start()
      try:
          stream_input = {"task": task, "thread_id": thread_id, "agent_memory": preload}
          # ... existing interrupt-resume loop, using stream_input ...
      finally:
          if memory is not None:
              await memory.stop()
      snapshot = await graph.aget_state(config)
      return AgentState.model_validate(snapshot.values)
  ```
  (Seed `agent_memory` via the initial input dict — `agent_memory` is last-write-wins, so the preload becomes the starting knowledge and flows into the system prompt.)

- [ ] **Step 4: Update other call sites** — every `build_default_app(...)` unpack must take 5 values now. Update `app/agent/demo.py::_demo`, and grep tests: `cd backend && grep -rn "build_default_app" tests app | cat`. Fix each unpack to `graph, emitter, store, sink, memory = build_default_app(...)` (or `*_`).

- [ ] **Step 5: Run tests** — `cd backend && uv run pytest tests/agent/test_memory_wiring.py -v` → PASS, then `cd backend && uv run pytest -q -m "not browser"` → full fast suite green.
- [ ] **Step 6: Commit** — `feat(memory): wire MEMORY.md — act enqueues, finalize appends run, run rehydrates`

---

## Track B — Context Compaction

### Task 4: `compact_for_llm()` (pure, no I/O, no LLM)

**Files:**
- Create: `backend/app/agent/compaction.py`
- Test: `backend/tests/agent/test_compaction.py`

**Interfaces:**
- Produces: `compact_for_llm(messages: list[BaseMessage], *, max_tool_chars: int = 2000) -> tuple[list[BaseMessage], dict]`. Returns `(compacted_messages, status)` where `status = {"messages_in", "messages_out", "dropped_observations", "truncated_tools"}`. Observation messages are identified by `isinstance(m, HumanMessage) and m.name == "observation"` (Task 5 makes the observe node set that name).

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/agent/test_compaction.py
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from app.agent.compaction import compact_for_llm


def _obs(text):  # an observation message as the observe node will tag it
    return HumanMessage(content=text, name="observation")


def test_drops_all_but_the_latest_observation():
    msgs = [
        _obs("page 1 [0] a [1] b"),
        AIMessage(content="click", tool_calls=[{"name": "Click", "args": {"index": 1}, "id": "t1"}]),
        ToolMessage(content="ok", tool_call_id="t1", name="Click"),
        _obs("page 2 [0] c [1] d"),
    ]
    out, status = compact_for_llm(msgs)
    obs = [m for m in out if isinstance(m, HumanMessage) and m.name == "observation"]
    assert len(obs) == 1 and "page 2" in obs[0].content   # only the freshest observation kept
    assert status["dropped_observations"] == 1
    # the action trail (AI tool call + its ToolMessage) is preserved
    assert any(isinstance(m, AIMessage) and m.tool_calls for m in out)
    assert any(isinstance(m, ToolMessage) and m.tool_call_id == "t1" for m in out)


def test_truncates_long_old_tool_output_but_not_recent():
    big = "x" * 5000
    msgs = [
        AIMessage(content="", tool_calls=[{"name": "Extract", "args": {}, "id": "t1"}]),
        ToolMessage(content=big, tool_call_id="t1", name="Extract"),   # old (before last obs)
        _obs("current page"),
        AIMessage(content="", tool_calls=[{"name": "Extract", "args": {}, "id": "t2"}]),
        ToolMessage(content=big, tool_call_id="t2", name="Extract"),   # recent (after last obs)
    ]
    out, status = compact_for_llm(msgs, max_tool_chars=2000)
    tool_contents = [m.content for m in out if isinstance(m, ToolMessage)]
    assert any(len(c) < 2100 and "truncated" in c for c in tool_contents)   # old one truncated
    assert any(len(c) == 5000 for c in tool_contents)                       # recent one intact
    assert status["truncated_tools"] == 1


def test_no_observations_is_a_noop():
    msgs = [AIMessage(content="hi"), HumanMessage(content="not an observation")]
    out, status = compact_for_llm(msgs)
    assert out == msgs and status["dropped_observations"] == 0
```

- [ ] **Step 2: Run tests, verify they fail** — `cd backend && uv run pytest tests/agent/test_compaction.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement `compaction.py`**

```python
# backend/app/agent/compaction.py
"""Layer 0+1 context compaction: drop superseded observations, truncate old tool outputs.

Old observations carry STALE element indices (the agent must act only on the freshest
observation — CLAUDE.md §3), so dropping them is both a token win and a correctness guard.
Layer 2 (LLM-summarize) is intentionally not here — it is a deferred fast-follow."""
from __future__ import annotations

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage


def _is_observation(m: BaseMessage) -> bool:
    return isinstance(m, HumanMessage) and getattr(m, "name", None) == "observation"


def compact_for_llm(
    messages: list[BaseMessage], *, max_tool_chars: int = 2000
) -> tuple[list[BaseMessage], dict]:
    obs_idxs = [i for i, m in enumerate(messages) if _is_observation(m)]
    last_obs = obs_idxs[-1] if obs_idxs else -1
    keep_obs = set(obs_idxs[-1:])

    out: list[BaseMessage] = []
    dropped = truncated = 0
    for i, m in enumerate(messages):
        if _is_observation(m) and i not in keep_obs:
            dropped += 1
            continue
        if (
            isinstance(m, ToolMessage)
            and i < last_obs
            and isinstance(m.content, str)
            and len(m.content) > max_tool_chars
        ):
            out.append(
                ToolMessage(
                    content=m.content[:max_tool_chars] + " …[truncated]",
                    tool_call_id=m.tool_call_id,
                    name=m.name,
                )
            )
            truncated += 1
            continue
        out.append(m)

    status = {
        "messages_in": len(messages),
        "messages_out": len(out),
        "dropped_observations": dropped,
        "truncated_tools": truncated,
    }
    return out, status
```

- [ ] **Step 4: Run tests, verify pass** — `cd backend && uv run pytest tests/agent/test_compaction.py -v` → PASS.
- [ ] **Step 5: Commit** — `feat(agent): compact_for_llm — drop stale observations, truncate old tool outputs`

---

### Task 5: Tag observations + apply compaction in the reason node + `context_status` event

**Files:**
- Modify: `backend/app/agent/nodes/observe.py` (set `name="observation"` on the emitted `HumanMessage`)
- Modify: `backend/app/agent/nodes/reason.py` (compact before the LLM call; emit `context_status`)
- Modify: `backend/app/events/protocol.py` (`CONTEXT_STATUS = "context_status"`) and `backend/app/events/emitter.py` (`emit_context_status`)
- Test: `backend/tests/agent/test_reason_compaction.py`

**Interfaces:**
- Consumes: `compact_for_llm` (Task 4); the emitter pattern from existing `emit_*` methods.
- Produces: the reason node sends `[system, *compacted]` to the LLM (never the raw full history) and emits a `context_status` event carrying the compaction `status` plus the call's real `input_tokens`.

- [ ] **Step 1: Write failing test** (drives a 2-turn run and asserts compaction shrank the LLM input + emitted the event)

```python
# backend/tests/agent/test_reason_compaction.py
from app.agent.demo import run
from app.config.container import build_default_app
from tests.fakes.fake_browser import FakeBrowserSession
from tests.fakes.fake_llm import FakeLLMClient, ai


async def test_old_observations_not_sent_to_llm_and_status_emitted():
    # 3 turns so >1 observation accumulates before the final LLM call
    llm = FakeLLMClient(turns=[
        ai("scroll", [{"name": "Scroll", "args": {"direction": "down"}, "id": "t1"}]),
        ai("scroll", [{"name": "Scroll", "args": {"direction": "down"}, "id": "t2"}]),
        ai("done", [{"name": "Complete", "args": {"success": True, "reason": "ok"}, "id": "c1"}]),
    ])
    graph, emitter, store, sink, _ = build_default_app(session=FakeBrowserSession(), llm=llm)
    await run(graph, task="t", thread_id="tc")

    # the LLM never received more than one observation message in any single call
    for call in llm.calls:                      # FakeLLMClient records the messages it was sent
        obs = [m for m in call if getattr(m, "name", None) == "observation"]
        assert len(obs) <= 1
    # a context_status event was emitted
    assert any(ev.event == "context_status" for ev in sink.events)
```

  (If `FakeLLMClient` does not already record received messages as `.calls`, add a `self.calls: list = []` that appends `messages` on each `complete()` — a 2-line change to `tests/fakes/fake_llm.py`. Read the fake first.)

- [ ] **Step 2: Run test, verify it fails** — `cd backend && uv run pytest tests/agent/test_reason_compaction.py -v` → FAIL (observe doesn't tag; reason sends full history; no event).

- [ ] **Step 3: Implement.**

  **3a. `observe.py`** — set the name on the observation message (both the plain-text and the vision list-content paths):
  ```python
  return {
      "observation": obs,
      "messages": [HumanMessage(content=content, name="observation")],
      "history": [StepRecord(step=state.step, node="observe")],
  }
  ```

  **3b. `protocol.py`** — add `CONTEXT_STATUS = "context_status"`.

  **3c. `emitter.py`** — import `CONTEXT_STATUS`; add:
  ```python
  async def emit_context_status(self, status: dict) -> None:
      await self._emit(CONTEXT_STATUS, status)
  ```

  **3d. `reason.py`** — compact before the call, emit status after (with real tokens):
  ```python
  from app.agent.compaction import compact_for_llm
  ...
  compacted, status = compact_for_llm(state.messages)
  system = build_system_message(state)
  ai = await llm.complete(messages=[system, *compacted], tools=TOOL_SPECS)
  status["input_tokens"] = getattr(ai, "input_tokens", None) or getattr(getattr(ai, "usage", None), "input_tokens", None)
  await emitter.emit_context_status(status)
  ```
  (Use whatever the existing reason node calls the LLM result + however it already reads usage/`input_tokens` for the `StepRecord`. Match that — do not invent a new usage path.)

- [ ] **Step 4: Run tests** — `cd backend && uv run pytest tests/agent/test_reason_compaction.py -v` → PASS, then `cd backend && uv run pytest -q -m "not browser"` → full fast suite green.
- [ ] **Step 5: Commit** — `feat(agent): tag observations, compact reason-node context, emit context_status`

---

## Execution Notes (waves)

- **Wave 1 (parallel):** Task 1 (memory document) ‖ Task 4 (compaction) — both pure, zero shared files.
- **Wave 2 (parallel):** Task 2 (AsyncMarkdownMemory, needs Task 1) ‖ Task 5 (observe/reason/events, needs Task 4).
- **Wave 3:** Task 3 (memory wiring, needs Task 2; touches `container`/`demo`/`act`/`graph`). Run alone — it changes the `build_default_app` arity that Task 5's tests also consume, so land Task 5 first or coordinate the 5-tuple unpack.
- **Final:** whole-branch review, then a live run (real OpenRouter + real browser) on a long task (e.g. the YouTube vision run) to confirm token-per-call stops growing and `runs/{thread_id}/memory.md` is written.

## Self-Review

- **Spec coverage:** Decision 11 + §7.2 (MEMORY.md doc, async non-blocking writer, enqueue on remember, append_run at finalize, rehydrate on resume) → Tasks 1–3. §7.5 (Layer 0 strip observations, Layer 1 truncate tool outputs, emit context_status, Layer 2 deferred) → Tasks 4–5. ✅
- **Deliberate refinement (noted):** the spec gates Layer 0 at "~95% of context window"; this plan drops superseded observations **unconditionally** because their element indices are stale and forbidden to reuse (CLAUDE.md §3) — so keeping them is never useful, only costly. If the user wants the 95%-gated behavior instead, Task 4 gains a token-threshold parameter; flagged for the execution handoff.
- **Type consistency:** `MemoryStore` methods (`start/stop/append/append_run/load`) are identical across Tasks 2–3 and the `FakeMemory` test double. `compact_for_llm(messages, *, max_tool_chars)` identical in Tasks 4–5. `name="observation"` tag set in Task 5 (observe) and read in Task 4 (compaction) — consistent. `build_default_app` 5-tuple return is applied in Task 3 and consumed in Task 3/5 tests.
- **Placeholder scan:** none — every code/test step carries full code.
