# Phase B1 — Agent Loop on Fakes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend's tool-calling ReAct agent loop in LangGraph — `observe → reason → act → (re-observe) → …` terminating on a `complete()` tool — running end-to-end against a scripted `FakeBrowserSession` and `FakeLLMClient`, with events and telemetry, but no real LLM, browser, funnel, or persistence.

**Architecture:** A `langgraph.graph.StateGraph` over a Pydantic `AgentState` (with an `add_messages` reducer). Three thin nodes (`observe`/`reason`/`act`) delegate to injected ports (`LLMClient`, `BrowserSession`, `EventSink`, `TrajectoryStore`). The LLM picks **structured tool calls**; a `ToolDispatcher` turns each tool call into an effect — browser tools build an `ActionCall` and call `BrowserSession.act()`; memory/control tools mutate state. The composition root wires fakes.

**Tech Stack:** Python 3.12+, LangGraph, langchain-core (messages + tools), Pydantic v2, pytest/pytest-asyncio. (All already in `backend/pyproject.toml` from Phase A — no new deps.)

## Global Constraints

- Work in `backend/`; tests run `cd backend && uv run pytest`. `pytest` has `pythonpath=["."]`, `asyncio_mode="auto"` (from Phase A) — `async def test_*` works directly.
- **Nodes are thin**: they call injected ports/services and return a **dict state delta**. No LLM/CDP/DB code inline in a node.
- **Actions are structured tool calls, never code execution.** A browser tool call maps 1:1 to an `ActionCall{name,args}` (from `browser_agent_contracts`) referencing elements by `index`.
- **Single source of truth is the graph state.** Never keep mutable agent state outside `AgentState`.
- **Never reuse previous-turn element indices** — `observe` rebuilds the `observation` every turn.
- **Think-before-act**: the `reason` node requires non-trivial reasoning (AIMessage `content`) accompanying tool calls; if missing, retry once, else fail `REASONING_MISSING`.
- **Explicit termination**: the loop ends only when the `complete(success, reason)` tool is called (→ `done`/`failed`), or on a typed failure (`NO_ACTION`, `MAX_STEPS`, `REASONING_MISSING`, `ACTION_TIMEOUT`). No "no tool calls = done".
- Contracts come from the installed `browser_agent_contracts` package: `Observation`, `Element`, `Viewport`, `ActionCall`, `ActionResult`, `PROTOCOL_VERSION`. **Do not redefine wire types.**
- YAGNI: no persistent memory file, no Jinja2 prompts, no real OpenRouter, no Playwright/funnel — those are B2–B4. In-RAM memory only (`agent_memory: dict`).
- Checkpointer import is `from langgraph.checkpoint.memory import InMemorySaver`.

### Shared spine (names/types every task must match)

```python
# ErrorCode (str Enum): ACTION_TIMEOUT, REASONING_MISSING, NO_ACTION, MAX_STEPS
# StepRecord(BaseModel): step:int, node:str, action:ActionCall|None, result:ActionResult|None,
#                        error_code:ErrorCode|None, input_tokens:int=0, output_tokens:int=0, latency_ms:float=0.0
# TabInfo(BaseModel): target_id:str, url:str, title:str="", active:bool=False
# LLMClient(Protocol):     async def complete(self, *, messages:list[BaseMessage], tools:Sequence[type[BaseModel]]) -> AIMessage
# BrowserSession(Protocol):async def observe(self,*,include_som:bool=True)->Observation; act(call:ActionCall)->ActionResult;
#                          navigate(url:str)->ActionResult; tabs()->list[TabInfo]
# EventSink(Protocol):     async def emit(self, event:"AgentEvent") -> None
# TrajectoryStore(Protocol): async def save(self, thread_id:str, record:StepRecord) -> None
# AgentState(BaseModel): task:str; messages:Annotated[list[BaseMessage],add_messages]; observation:Observation|None;
#   agent_memory:dict[str,str]; history:Annotated[list[StepRecord],operator.add]; last_action:ActionCall|None;
#   last_result:ActionResult|None; status:Literal["running","done","failed"]; error_code:ErrorCode|None;
#   step:int; finished:bool; success:bool|None; reason:str; nudge_count:int; thread_id:str
# Tool specs (Pydantic arg-schema classes; class name == tool-call name): Navigate, Click, TypeText, Scroll,
#   Extract, WaitFor, Remember, Recall, SetPlan, Complete
# ToolDispatcher.dispatch(tool_call, *, state, session, emitter) -> tuple[ToolMessage, dict]   # (msg, state-delta)
```

---

### Task 1: Telemetry records + the four ports

**Files:**
- Create: `backend/app/telemetry/records.py`, `backend/app/telemetry/store.py`
- Create: `backend/app/llm/base.py`, `backend/app/browser/base.py`, `backend/app/events/sink.py`
- Test: `backend/tests/agent/test_ports.py`

**Interfaces:**
- Consumes: `browser_agent_contracts` (`Observation`, `ActionCall`, `ActionResult`).
- Produces: `ErrorCode`, `StepRecord`, `TabInfo`, and the `LLMClient` / `BrowserSession` / `EventSink` / `TrajectoryStore` Protocols + an in-memory `InMemoryTrajectoryStore`.

- [ ] **Step 1: Write the failing test `backend/tests/agent/test_ports.py`**

```python
import pytest
from browser_agent_contracts import ActionCall, ActionResult
from app.telemetry.records import ErrorCode, StepRecord, TabInfo
from app.telemetry.store import InMemoryTrajectoryStore


def test_error_codes_exist():
    assert ErrorCode.REASONING_MISSING.value == "REASONING_MISSING"
    assert {e.value for e in ErrorCode} >= {"ACTION_TIMEOUT", "NO_ACTION", "MAX_STEPS"}


def test_step_record_defaults():
    rec = StepRecord(step=1, node="act", action=ActionCall(name="click", args={"index": 5}))
    assert rec.input_tokens == 0 and rec.error_code is None
    assert rec.action.args["index"] == 5


async def test_in_memory_trajectory_store_saves():
    store = InMemoryTrajectoryStore()
    await store.save("t1", StepRecord(step=1, node="observe"))
    await store.save("t1", StepRecord(step=2, node="reason"))
    assert [r.step for r in store.records["t1"]] == [1, 2]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/agent/test_ports.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.telemetry.records'`.

- [ ] **Step 3: Create `backend/app/telemetry/records.py`**

```python
from __future__ import annotations

from enum import Enum

from browser_agent_contracts import ActionCall, ActionResult
from pydantic import BaseModel


class ErrorCode(str, Enum):
    ACTION_TIMEOUT = "ACTION_TIMEOUT"
    REASONING_MISSING = "REASONING_MISSING"
    NO_ACTION = "NO_ACTION"
    MAX_STEPS = "MAX_STEPS"


class StepRecord(BaseModel):
    step: int
    node: str
    action: ActionCall | None = None
    result: ActionResult | None = None
    error_code: ErrorCode | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0


class TabInfo(BaseModel):
    target_id: str
    url: str
    title: str = ""
    active: bool = False
```

- [ ] **Step 4: Create `backend/app/telemetry/store.py`**

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .records import StepRecord


@runtime_checkable
class TrajectoryStore(Protocol):
    async def save(self, thread_id: str, record: StepRecord) -> None: ...


class InMemoryTrajectoryStore:
    """Dev/test TrajectoryStore — keeps records per thread in RAM."""

    def __init__(self) -> None:
        self.records: dict[str, list[StepRecord]] = {}

    async def save(self, thread_id: str, record: StepRecord) -> None:
        self.records.setdefault(thread_id, []).append(record)
```

- [ ] **Step 5: Create `backend/app/llm/base.py`**

```python
from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from langchain_core.messages import AIMessage, BaseMessage
from pydantic import BaseModel


@runtime_checkable
class LLMClient(Protocol):
    """Returns the model's next turn as an AIMessage (content = reasoning, tool_calls = actions)."""

    async def complete(
        self, *, messages: list[BaseMessage], tools: Sequence[type[BaseModel]]
    ) -> AIMessage: ...
```

- [ ] **Step 6: Create `backend/app/browser/base.py`**

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

from browser_agent_contracts import ActionCall, ActionResult, Observation

from app.telemetry.records import TabInfo


@runtime_checkable
class BrowserSession(Protocol):
    async def observe(self, *, include_som: bool = True) -> Observation: ...
    async def act(self, call: ActionCall) -> ActionResult: ...
    async def navigate(self, url: str) -> ActionResult: ...
    async def tabs(self) -> list[TabInfo]: ...
```

- [ ] **Step 7: Create `backend/app/events/sink.py`**

```python
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from app.events.protocol import AgentEvent


@runtime_checkable
class EventSink(Protocol):
    async def emit(self, event: "AgentEvent") -> None: ...


class BufferSink:
    """Dev/test EventSink — collects events in a list."""

    def __init__(self) -> None:
        self.events: list = []

    async def emit(self, event) -> None:
        self.events.append(event)
```

- [ ] **Step 8: Run to verify it passes**

Run: `cd backend && uv run pytest tests/agent/test_ports.py -v`
Expected: PASS — 3 passed. (Create empty `backend/tests/agent/__init__.py` if pytest can't collect the package.)

- [ ] **Step 9: Commit**

```bash
git add backend/app/telemetry backend/app/llm/base.py backend/app/browser/base.py backend/app/events/sink.py backend/tests/agent
git commit -m "feat(agent): telemetry records + LLMClient/BrowserSession/EventSink/TrajectoryStore ports"
```

---

### Task 2: AgentState

**Files:**
- Create: `backend/app/agent/state.py`
- Test: `backend/tests/agent/test_state.py`

**Interfaces:**
- Consumes: `browser_agent_contracts` (`Observation`, `ActionCall`, `ActionResult`); `app.telemetry.records` (`StepRecord`, `ErrorCode`).
- Produces: `AgentState` (Pydantic `BaseModel`) — the single graph state, with `messages` (`add_messages`) and `history` (`operator.add`) reducers, defaulting `status="running"`, `step=0`, `nudge_count=0`, `finished=False`.

- [ ] **Step 1: Write the failing test `backend/tests/agent/test_state.py`**

```python
from langchain_core.messages import HumanMessage
from app.agent.state import AgentState
from app.telemetry.records import StepRecord


def test_state_defaults_and_construction():
    s = AgentState(task="log in", thread_id="t1")
    assert s.status == "running" and s.step == 0 and s.nudge_count == 0
    assert s.finished is False and s.success is None and s.agent_memory == {}
    assert s.messages == [] and s.history == []


def test_add_messages_reducer_appends():
    # Simulate LangGraph merging a delta: build state, then validate the reducer is wired.
    s = AgentState(task="x", thread_id="t1", messages=[HumanMessage(content="hi")])
    assert s.messages[0].content == "hi"


def test_history_accepts_step_records():
    s = AgentState(task="x", thread_id="t1", history=[StepRecord(step=1, node="observe")])
    assert s.history[0].node == "observe"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/agent/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.agent.state'`.

- [ ] **Step 3: Create `backend/app/agent/state.py`**

```python
from __future__ import annotations

import operator
from typing import Annotated, Literal

from browser_agent_contracts import ActionCall, ActionResult, Observation
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field

from app.telemetry.records import ErrorCode, StepRecord


class AgentState(BaseModel):
    """Single source of truth flowing through the agent graph."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    task: str
    thread_id: str

    messages: Annotated[list[BaseMessage], add_messages] = Field(default_factory=list)
    observation: Observation | None = None
    agent_memory: dict[str, str] = Field(default_factory=dict)
    history: Annotated[list[StepRecord], operator.add] = Field(default_factory=list)

    last_action: ActionCall | None = None
    last_result: ActionResult | None = None

    status: Literal["running", "done", "failed"] = "running"
    error_code: ErrorCode | None = None
    step: int = 0
    nudge_count: int = 0
    finished: bool = False
    success: bool | None = None
    reason: str = ""
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && uv run pytest tests/agent/test_state.py -v`
Expected: PASS — 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/state.py backend/tests/agent/test_state.py
git commit -m "feat(agent): AgentState (Pydantic, add_messages + history reducers)"
```

---

### Task 3: Events — protocol + emitter

**Files:**
- Create: `backend/app/events/protocol.py`, `backend/app/events/emitter.py`
- Test: `backend/tests/agent/test_events.py`

**Interfaces:**
- Consumes: `app.events.sink.BufferSink`.
- Produces: `AgentEvent{type:str, data:dict, ts:str}`; the event-type constants `STATUS, REASONING, TOOL_CALL, OBSERVATION, USAGE, PLAN_UPDATE, MEMORY_UPDATE, ERROR, FINALIZE`; `EventEmitter` with `await emit_reasoning(text)`, `emit_tool_call(name, args)`, `emit_observation(url, n_elements)`, `emit_plan(steps)`, `emit_memory(key)`, `emit_error(msg)`, `emit_finalize(success, reason)`, each pushing one `AgentEvent` to the injected `EventSink`.

- [ ] **Step 1: Write the failing test `backend/tests/agent/test_events.py`**

```python
from app.events.sink import BufferSink
from app.events.emitter import EventEmitter
from app.events.protocol import TOOL_CALL, REASONING


async def test_emitter_pushes_typed_events_to_sink():
    sink = BufferSink()
    em = EventEmitter(sink)
    await em.emit_reasoning("I will click login")
    await em.emit_tool_call("Click", {"index": 5})
    types = [e.type for e in sink.events]
    assert types == [REASONING, TOOL_CALL]
    assert sink.events[1].data == {"name": "Click", "args": {"index": 5}}
    assert isinstance(sink.events[0].ts, str) and sink.events[0].ts
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/agent/test_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.events.protocol'`.

- [ ] **Step 3: Create `backend/app/events/protocol.py`**

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

STATUS = "status"
REASONING = "reasoning"
TOOL_CALL = "tool_call"
OBSERVATION = "observation"
USAGE = "usage"
PLAN_UPDATE = "plan_update"
MEMORY_UPDATE = "memory_update"
ERROR = "error"
FINALIZE = "finalize"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentEvent(BaseModel):
    type: str
    data: dict[str, Any] = Field(default_factory=dict)
    ts: str = Field(default_factory=_now_iso)
```

- [ ] **Step 4: Create `backend/app/events/emitter.py`**

```python
from __future__ import annotations

from typing import Any

from app.events.protocol import (
    AgentEvent,
    ERROR,
    FINALIZE,
    MEMORY_UPDATE,
    OBSERVATION,
    PLAN_UPDATE,
    REASONING,
    STATUS,
    TOOL_CALL,
)
from app.events.sink import EventSink


class EventEmitter:
    """Builds typed AgentEvents and forwards them to the injected sink."""

    def __init__(self, sink: EventSink) -> None:
        self._sink = sink

    async def _emit(self, type_: str, data: dict[str, Any]) -> None:
        await self._sink.emit(AgentEvent(type=type_, data=data))

    async def emit_status(self, phase: str, message: str) -> None:
        await self._emit(STATUS, {"phase": phase, "message": message})

    async def emit_reasoning(self, text: str) -> None:
        await self._emit(REASONING, {"text": text})

    async def emit_tool_call(self, name: str, args: dict[str, Any]) -> None:
        await self._emit(TOOL_CALL, {"name": name, "args": args})

    async def emit_observation(self, url: str, n_elements: int) -> None:
        await self._emit(OBSERVATION, {"url": url, "elements": n_elements})

    async def emit_plan(self, steps: list[str]) -> None:
        await self._emit(PLAN_UPDATE, {"steps": steps})

    async def emit_memory(self, key: str) -> None:
        await self._emit(MEMORY_UPDATE, {"key": key})

    async def emit_error(self, message: str) -> None:
        await self._emit(ERROR, {"message": message})

    async def emit_finalize(self, success: bool, reason: str) -> None:
        await self._emit(FINALIZE, {"success": success, "reason": reason})
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd backend && uv run pytest tests/agent/test_events.py -v`
Expected: PASS — 1 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/events/protocol.py backend/app/events/emitter.py backend/tests/agent/test_events.py
git commit -m "feat(agent): event protocol + EventEmitter over EventSink"
```

---

### Task 4: Tool specs + descriptions

**Files:**
- Create: `backend/app/tools/specs.py`
- Test: `backend/tests/agent/test_tool_specs.py`

**Interfaces:**
- Produces: Pydantic arg-schema classes whose **class name is the tool-call name** — `Navigate(url:str)`, `Click(index:int)`, `TypeText(index:int, text:str)`, `Scroll(direction:Literal["up","down"], amount:int=1)`, `Extract(query:str)`, `WaitFor(seconds:float=1.0)`, `Remember(key:str, value:str)`, `Recall()`, `SetPlan(steps:list[str])`, `Complete(success:bool, reason:str)`. A `TOOL_SPECS: list[type[BaseModel]]` list and `tool_descriptions() -> str` producing `- Name(args): <docstring>` lines. A `BROWSER_TOOLS`/`CONTROL_TOOLS`/`MEMORY_TOOLS` name-set for the dispatcher.

- [ ] **Step 1: Write the failing test `backend/tests/agent/test_tool_specs.py`**

```python
from app.tools.specs import TOOL_SPECS, tool_descriptions, Click, Complete


def test_specs_have_expected_names():
    names = {s.__name__ for s in TOOL_SPECS}
    assert names == {
        "Navigate", "Click", "TypeText", "Scroll", "Extract",
        "WaitFor", "Remember", "Recall", "SetPlan", "Complete",
    }


def test_click_schema_fields():
    c = Click(index=5)
    assert c.index == 5
    assert Complete(success=True, reason="done").success is True


def test_tool_descriptions_render_one_line_per_tool():
    text = tool_descriptions()
    assert "- Click(index): " in text
    assert "- Complete(success, reason): " in text
    assert text.count("\n- ") + 1 == len(TOOL_SPECS)  # one bullet per tool
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/agent/test_tool_specs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.tools.specs'`.

- [ ] **Step 3: Create `backend/app/tools/specs.py`**

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Navigate(BaseModel):
    """Navigate the active tab to a URL."""
    url: str = Field(description="Absolute URL to open")


class Click(BaseModel):
    """Click the element with the given [N] index from the current observation."""
    index: int = Field(description="The element index to click")


class TypeText(BaseModel):
    """Type text into the element with the given index."""
    index: int
    text: str


class Scroll(BaseModel):
    """Scroll the page up or down by `amount` viewport steps."""
    direction: Literal["up", "down"]
    amount: int = 1


class Extract(BaseModel):
    """Read text/answer a question from the current page without acting."""
    query: str


class WaitFor(BaseModel):
    """Wait for the page to settle for `seconds` before re-observing."""
    seconds: float = 1.0


class Remember(BaseModel):
    """Save a durable key/value note to working memory for later steps."""
    key: str
    value: str


class Recall(BaseModel):
    """Return everything currently in working memory."""


class SetPlan(BaseModel):
    """Set or replace the step-by-step plan shown to the user."""
    steps: list[str]


class Complete(BaseModel):
    """Finish the task. success=True if the goal was achieved, with a short reason."""
    success: bool
    reason: str


TOOL_SPECS: list[type[BaseModel]] = [
    Navigate, Click, TypeText, Scroll, Extract,
    WaitFor, Remember, Recall, SetPlan, Complete,
]

BROWSER_TOOLS = {"Navigate", "Click", "TypeText", "Scroll", "Extract", "WaitFor"}
MEMORY_TOOLS = {"Remember", "Recall"}
CONTROL_TOOLS = {"SetPlan", "Complete"}


def tool_descriptions() -> str:
    """Render `- Name(arg1, arg2): <docstring first line>` for each tool spec."""
    lines: list[str] = []
    for spec in TOOL_SPECS:
        args = ", ".join(spec.model_fields.keys())
        doc = (spec.__doc__ or "").strip().splitlines()[0] if spec.__doc__ else ""
        lines.append(f"- {spec.__name__}({args}): {doc}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && uv run pytest tests/agent/test_tool_specs.py -v`
Expected: PASS — 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/specs.py backend/tests/agent/test_tool_specs.py
git commit -m "feat(tools): Pydantic tool-call specs + tool_descriptions"
```

---

### Task 5: ToolDispatcher

**Files:**
- Create: `backend/app/tools/dispatcher.py`
- Test: `backend/tests/agent/test_dispatcher.py`

**Interfaces:**
- Consumes: `app.tools.specs` (name-sets), `app.agent.state.AgentState`, `app.browser.base.BrowserSession`, `app.events.emitter.EventEmitter`, `browser_agent_contracts` (`ActionCall`/`ActionResult`).
- Produces: `ToolDispatcher.dispatch(tool_call: dict, *, state, session, emitter) -> tuple[ToolMessage, dict]` where `tool_call` is `{"name","args","id"}`. Returns the `ToolMessage` (with `tool_call_id`) and a **state delta dict** to merge (e.g. `{"last_action":..., "last_result":..., "agent_memory":..., "finished":..., "success":..., "reason":...}`). Browser tools build `ActionCall` (name lowercased: `Click→click`, `TypeText→type`, `WaitFor→wait_for`) and `await session.act(...)`. `Remember` merges memory; `Recall` returns memory text; `Complete` sets terminal fields; `SetPlan` emits a plan event.

- [ ] **Step 1: Write the failing test `backend/tests/agent/test_dispatcher.py`**

```python
import pytest
from browser_agent_contracts import ActionCall, ActionResult, Observation, Viewport
from langchain_core.messages import ToolMessage

from app.agent.state import AgentState
from app.events.emitter import EventEmitter
from app.events.sink import BufferSink
from app.tools.dispatcher import ToolDispatcher


class _RecordingSession:
    def __init__(self):
        self.calls: list[ActionCall] = []
    async def observe(self, *, include_som=True):
        return Observation(url="about:blank", viewport=Viewport(width=1, height=1))
    async def act(self, call: ActionCall) -> ActionResult:
        self.calls.append(call)
        return ActionResult(success=True, reason=f"did {call.name}")
    async def navigate(self, url): return ActionResult(success=True, reason="nav")
    async def tabs(self): return []


def _state():
    return AgentState(task="t", thread_id="t1")


async def test_click_builds_actioncall_and_calls_session():
    d = ToolDispatcher()
    sess = _RecordingSession()
    msg, delta = await d.dispatch(
        {"name": "Click", "args": {"index": 5}, "id": "c1"},
        state=_state(), session=sess, emitter=EventEmitter(BufferSink()),
    )
    assert sess.calls[0] == ActionCall(name="click", args={"index": 5})
    assert isinstance(msg, ToolMessage) and msg.tool_call_id == "c1"
    assert delta["last_action"].name == "click" and delta["last_result"].success is True


async def test_remember_merges_into_agent_memory():
    d = ToolDispatcher()
    msg, delta = await d.dispatch(
        {"name": "Remember", "args": {"key": "login_url", "value": "/auth"}, "id": "r1"},
        state=_state(), session=_RecordingSession(), emitter=EventEmitter(BufferSink()),
    )
    assert delta["agent_memory"] == {"login_url": "/auth"}
    assert "login_url" in msg.content


async def test_complete_sets_terminal_fields():
    d = ToolDispatcher()
    msg, delta = await d.dispatch(
        {"name": "Complete", "args": {"success": True, "reason": "logged in"}, "id": "k1"},
        state=_state(), session=_RecordingSession(), emitter=EventEmitter(BufferSink()),
    )
    assert delta == {"finished": True, "success": True, "reason": "logged in"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/agent/test_dispatcher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.tools.dispatcher'`.

- [ ] **Step 3: Create `backend/app/tools/dispatcher.py`**

```python
from __future__ import annotations

from typing import Any

from browser_agent_contracts import ActionCall
from langchain_core.messages import ToolMessage

from app.agent.state import AgentState
from app.browser.base import BrowserSession
from app.events.emitter import EventEmitter

# tool-call name -> ActionCall name
_BROWSER_ACTION = {
    "Navigate": "navigate",
    "Click": "click",
    "TypeText": "type",
    "Scroll": "scroll",
    "Extract": "extract",
    "WaitFor": "wait_for",
}


class ToolDispatcher:
    """Turns one structured tool call into an effect + a ToolMessage + a state delta."""

    async def dispatch(
        self,
        tool_call: dict[str, Any],
        *,
        state: AgentState,
        session: BrowserSession,
        emitter: EventEmitter,
    ) -> tuple[ToolMessage, dict[str, Any]]:
        name = tool_call["name"]
        args = tool_call.get("args", {}) or {}
        call_id = tool_call["id"]
        await emitter.emit_tool_call(name, args)

        if name in _BROWSER_ACTION:
            call = ActionCall(name=_BROWSER_ACTION[name], args=args)
            result = await session.act(call)
            content = result.reason or ("ok" if result.success else "failed")
            return (
                ToolMessage(content=content, tool_call_id=call_id, name=name),
                {"last_action": call, "last_result": result},
            )

        if name == "Remember":
            merged = {**state.agent_memory, args["key"]: args["value"]}
            await emitter.emit_memory(args["key"])
            return (
                ToolMessage(content=f"Remembered: {args['key']}", tool_call_id=call_id, name=name),
                {"agent_memory": merged},
            )

        if name == "Recall":
            text = "\n".join(f"- {k}: {v}" for k, v in state.agent_memory.items()) or "(empty)"
            return ToolMessage(content=text, tool_call_id=call_id, name=name), {}

        if name == "SetPlan":
            steps = list(args.get("steps", []))
            await emitter.emit_plan(steps)
            return (
                ToolMessage(content=f"Plan set ({len(steps)} steps)", tool_call_id=call_id, name=name),
                {},
            )

        if name == "Complete":
            return (
                ToolMessage(content="Task marked complete", tool_call_id=call_id, name=name),
                {"finished": True, "success": bool(args["success"]), "reason": args.get("reason", "")},
            )

        return ToolMessage(content=f"Unknown tool: {name}", tool_call_id=call_id, name=name), {}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && uv run pytest tests/agent/test_dispatcher.py -v`
Expected: PASS — 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/dispatcher.py backend/tests/agent/test_dispatcher.py
git commit -m "feat(tools): ToolDispatcher (tool_call -> ActionCall/effect + state delta)"
```

---

### Task 6: Fakes (FakeBrowserSession + FakeLLMClient)

**Files:**
- Create: `backend/tests/fakes/__init__.py`, `backend/tests/fakes/fake_browser.py`, `backend/tests/fakes/fake_llm.py`
- Test: `backend/tests/agent/test_fakes.py`

**Interfaces:**
- Produces: `FakeBrowserSession(observations: list[Observation] | None=None)` — `observe()` returns the next scripted observation (or a default blank page), records `acts: list[ActionCall]`, `act()` returns a scripted/default-success `ActionResult`. `FakeLLMClient(turns: list[AIMessage])` — `complete()` pops the next scripted `AIMessage`; raises if exhausted. A helper `ai(content: str, tool_calls: list[dict]) -> AIMessage`.

- [ ] **Step 1: Write the failing test `backend/tests/agent/test_fakes.py`**

```python
import pytest
from browser_agent_contracts import ActionCall, Observation, Viewport
from app.browser.base import BrowserSession
from app.llm.base import LLMClient
from tests.fakes.fake_browser import FakeBrowserSession
from tests.fakes.fake_llm import FakeLLMClient, ai


async def test_fake_browser_satisfies_port_and_records_acts():
    obs = Observation(url="https://x", viewport=Viewport(width=2, height=2))
    sess = FakeBrowserSession(observations=[obs])
    assert isinstance(sess, BrowserSession)
    assert (await sess.observe()).url == "https://x"
    await sess.act(ActionCall(name="click", args={"index": 1}))
    assert sess.acts[0].args["index"] == 1


async def test_fake_llm_pops_scripted_turns():
    llm = FakeLLMClient(turns=[ai("thinking", [{"name": "Complete", "args": {"success": True, "reason": "ok"}, "id": "1"}])])
    assert isinstance(llm, LLMClient)
    msg = await llm.complete(messages=[], tools=[])
    assert msg.tool_calls[0]["name"] == "Complete"
    with pytest.raises(IndexError):
        await llm.complete(messages=[], tools=[])
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/agent/test_fakes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tests.fakes.fake_browser'`.

- [ ] **Step 3: Create `backend/tests/fakes/__init__.py`** (empty file)

```python
```

- [ ] **Step 4: Create `backend/tests/fakes/fake_browser.py`**

```python
from __future__ import annotations

from browser_agent_contracts import ActionCall, ActionResult, Observation, Viewport


def _blank() -> Observation:
    return Observation(url="about:blank", title="", viewport=Viewport(width=1280, height=800))


class FakeBrowserSession:
    """Scripted BrowserSession for graph tests. Records every act()."""

    def __init__(self, observations: list[Observation] | None = None,
                 results: list[ActionResult] | None = None) -> None:
        self._obs = list(observations or [])
        self._results = list(results or [])
        self.acts: list[ActionCall] = []

    async def observe(self, *, include_som: bool = True) -> Observation:
        return self._obs.pop(0) if self._obs else _blank()

    async def act(self, call: ActionCall) -> ActionResult:
        self.acts.append(call)
        return self._results.pop(0) if self._results else ActionResult(success=True, reason="ok")

    async def navigate(self, url: str) -> ActionResult:
        return await self.act(ActionCall(name="navigate", args={"url": url}))

    async def tabs(self):
        return []
```

- [ ] **Step 5: Create `backend/tests/fakes/fake_llm.py`**

```python
from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage
from pydantic import BaseModel
from typing import Sequence


def ai(content: str, tool_calls: list[dict] | None = None) -> AIMessage:
    return AIMessage(content=content, tool_calls=tool_calls or [])


class FakeLLMClient:
    """Pops scripted AIMessages in order; raises IndexError when exhausted."""

    def __init__(self, turns: list[AIMessage]) -> None:
        self._turns = list(turns)
        self.calls = 0

    async def complete(self, *, messages: list[BaseMessage], tools: Sequence[type[BaseModel]]) -> AIMessage:
        self.calls += 1
        return self._turns.pop(0)
```

- [ ] **Step 6: Run to verify it passes**

Run: `cd backend && uv run pytest tests/agent/test_fakes.py -v`
Expected: PASS — 2 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/tests/fakes backend/tests/agent/test_fakes.py
git commit -m "test(agent): FakeBrowserSession + FakeLLMClient satisfying the ports"
```

---

### Task 7: `observe` node

**Files:**
- Create: `backend/app/agent/format.py`, `backend/app/agent/nodes/__init__.py`, `backend/app/agent/nodes/observe.py`
- Test: `backend/tests/agent/test_observe_node.py`

**Interfaces:**
- Consumes: `BrowserSession`, `EventEmitter`, `AgentState`, `Observation`.
- Produces: `format_observation(obs: Observation) -> str` (a numbered element list + url/title header); `build_observe_node(session, emitter)` → an async node `observe(state) -> dict` returning `{"observation": obs, "messages": [HumanMessage(...)], "history": [StepRecord(node="observe", ...)]}` and emitting an observation event.

- [ ] **Step 1: Write the failing test `backend/tests/agent/test_observe_node.py`**

```python
from browser_agent_contracts import Element, Observation, Viewport
from langchain_core.messages import HumanMessage
from app.agent.state import AgentState
from app.agent.format import format_observation
from app.agent.nodes.observe import build_observe_node
from app.events.emitter import EventEmitter
from app.events.sink import BufferSink
from tests.fakes.fake_browser import FakeBrowserSession


def test_format_observation_numbers_elements():
    obs = Observation(
        url="https://x", title="X", viewport=Viewport(width=1, height=1),
        elements=[Element(index=1, role="button", name="Login"),
                  Element(index=2, role="textbox", name="Email")],
    )
    text = format_observation(obs)
    assert "https://x" in text and "[1] button" in text and "Login" in text and "[2] textbox" in text


async def test_observe_node_writes_observation_and_message():
    obs = Observation(url="https://x", viewport=Viewport(width=1, height=1),
                      elements=[Element(index=1, role="button", name="Go")])
    sink = BufferSink()
    node = build_observe_node(FakeBrowserSession(observations=[obs]), EventEmitter(sink))
    delta = await node(AgentState(task="t", thread_id="t1"))
    assert delta["observation"].url == "https://x"
    assert isinstance(delta["messages"][0], HumanMessage) and "[1] button" in delta["messages"][0].content
    assert delta["history"][0].node == "observe"
    assert any(e.type == "observation" for e in sink.events)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/agent/test_observe_node.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.agent.format'`.

- [ ] **Step 3: Create `backend/app/agent/format.py`**

```python
from __future__ import annotations

from browser_agent_contracts import Observation


def format_observation(obs: Observation) -> str:
    """Render the compact, numbered element list the model reads each turn."""
    header = f"Current page: {obs.url}"
    if obs.title:
        header += f" — {obs.title}"
    lines = [header, "Interactable elements:"]
    for el in obs.elements:
        label = f"[{el.index}] {el.role}"
        if el.name:
            label += f' "{el.name}"'
        if el.value:
            label += f" = {el.value!r}"
        lines.append(label)
    if not obs.elements:
        lines.append("(none)")
    if obs.dropped_count:
        lines.append(f"({obs.dropped_count} lower-priority elements hidden — scroll to reveal)")
    return "\n".join(lines)
```

- [ ] **Step 4: Create `backend/app/agent/nodes/__init__.py`** (empty file)

```python
```

- [ ] **Step 5: Create `backend/app/agent/nodes/observe.py`**

```python
from __future__ import annotations

from langchain_core.messages import HumanMessage

from app.agent.format import format_observation
from app.agent.state import AgentState
from app.browser.base import BrowserSession
from app.events.emitter import EventEmitter
from app.telemetry.records import StepRecord


def build_observe_node(session: BrowserSession, emitter: EventEmitter):
    async def observe(state: AgentState) -> dict:
        obs = await session.observe()
        await emitter.emit_observation(obs.url, len(obs.elements))
        return {
            "observation": obs,
            "messages": [HumanMessage(content=format_observation(obs))],
            "history": [StepRecord(step=state.step, node="observe")],
        }

    return observe
```

- [ ] **Step 6: Run to verify it passes**

Run: `cd backend && uv run pytest tests/agent/test_observe_node.py -v`
Expected: PASS — 2 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/agent/format.py backend/app/agent/nodes/__init__.py backend/app/agent/nodes/observe.py backend/tests/agent/test_observe_node.py
git commit -m "feat(agent): observe node + observation formatter"
```

---

### Task 8: `reason` node (think-before-act enforcement)

**Files:**
- Create: `backend/app/agent/prompt.py`, `backend/app/agent/nodes/reason.py`
- Test: `backend/tests/agent/test_reason_node.py`

**Interfaces:**
- Consumes: `LLMClient`, `EventEmitter`, `AgentState`, `TOOL_SPECS`, `tool_descriptions`.
- Produces: `SYSTEM_PROMPT` (a plain string for B1; Jinja2 comes in B2) + `build_system_message(state) -> SystemMessage`; `build_reason_node(llm, emitter)` → async `reason(state) -> dict`. Behavior: if the last message is an `AIMessage` with no `tool_calls` (a re-entry/nudge), append a reminder `HumanMessage` and increment `nudge_count` first. Call `llm.complete(messages=[system, *state.messages], tools=TOOL_SPECS)`. **Reasoning enforcement:** if the returned message has `tool_calls` but trivial/empty `content`, retry once with a "explain your reasoning first" reminder; if still trivial → return `{"status":"failed","error_code":REASONING_MISSING,"finished":True}`. Otherwise emit reasoning, increment `step`, return `{"messages":[ai], "step": state.step+1, "history":[StepRecord(...usage...)]}`.

- [ ] **Step 1: Write the failing test `backend/tests/agent/test_reason_node.py`**

```python
from langchain_core.messages import AIMessage, HumanMessage
from app.agent.state import AgentState
from app.agent.nodes.reason import build_reason_node
from app.events.emitter import EventEmitter
from app.events.sink import BufferSink
from app.telemetry.records import ErrorCode
from tests.fakes.fake_llm import FakeLLMClient, ai


async def test_reason_emits_ai_message_with_tool_call():
    llm = FakeLLMClient(turns=[ai("I will click Login", [{"name": "Click", "args": {"index": 1}, "id": "1"}])])
    node = build_reason_node(llm, EventEmitter(BufferSink()))
    state = AgentState(task="t", thread_id="t1", messages=[HumanMessage(content="page")])
    delta = await node(state)
    assert delta["step"] == 1
    assert delta["messages"][0].tool_calls[0]["name"] == "Click"


async def test_reason_missing_reasoning_retries_then_fails():
    # both turns return a tool call with empty content -> REASONING_MISSING after one retry
    llm = FakeLLMClient(turns=[
        ai("", [{"name": "Click", "args": {"index": 1}, "id": "1"}]),
        ai("   ", [{"name": "Click", "args": {"index": 1}, "id": "2"}]),
    ])
    node = build_reason_node(llm, EventEmitter(BufferSink()))
    delta = await node(AgentState(task="t", thread_id="t1", messages=[HumanMessage(content="page")]))
    assert delta["status"] == "failed" and delta["error_code"] == ErrorCode.REASONING_MISSING
    assert delta["finished"] is True
    assert llm.calls == 2  # retried exactly once
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/agent/test_reason_node.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.agent.prompt'`.

- [ ] **Step 3: Create `backend/app/agent/prompt.py`**

```python
from __future__ import annotations

from langchain_core.messages import SystemMessage

from app.agent.state import AgentState
from app.tools.specs import tool_descriptions

SYSTEM_PROMPT = """You are a web browser agent. Each turn you receive the current page as a \
numbered list of interactable elements. Think step by step in plain text FIRST, then call exactly \
one tool to act. Refer to elements by their [N] index. When the task is achieved (or impossible), \
call Complete(success, reason).

Available tools:
{tools}

Working memory:
{memory}
"""


def build_system_message(state: AgentState) -> SystemMessage:
    memory = "\n".join(f"- {k}: {v}" for k, v in state.agent_memory.items()) or "(empty)"
    return SystemMessage(content=SYSTEM_PROMPT.format(tools=tool_descriptions(), memory=memory))
```

- [ ] **Step 4: Create `backend/app/agent/nodes/reason.py`**

```python
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.prompt import build_system_message
from app.agent.state import AgentState
from app.events.emitter import EventEmitter
from app.llm.base import LLMClient
from app.telemetry.records import ErrorCode, StepRecord
from app.tools.specs import TOOL_SPECS

_REMINDER = (
    "Before acting you must explain your reasoning in plain text. "
    "Describe the next step, THEN call one tool."
)


def _text(msg: AIMessage) -> str:
    return msg.content if isinstance(msg.content, str) else " ".join(
        b.get("text", "") for b in msg.content if isinstance(b, dict)
    )


def _has_reasoning(msg: AIMessage) -> bool:
    return len(_text(msg).strip()) >= 3


def _usage(msg: AIMessage) -> tuple[int, int]:
    u = getattr(msg, "usage_metadata", None) or {}
    return int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0))


def build_reason_node(llm: LLMClient, emitter: EventEmitter):
    async def reason(state: AgentState) -> dict:
        messages = list(state.messages)
        nudge_delta: dict = {}

        # Re-entry nudge: last turn produced no tool call.
        last = messages[-1] if messages else None
        if isinstance(last, AIMessage) and not last.tool_calls:
            messages.append(HumanMessage(content="You did not call any tool. Call a tool or Complete()."))
            nudge_delta = {"nudge_count": state.nudge_count + 1}

        system = build_system_message(state)
        ai = await llm.complete(messages=[system, *messages], tools=TOOL_SPECS)

        # Think-before-act enforcement: retry once if a tool call lacks reasoning.
        if ai.tool_calls and not _has_reasoning(ai):
            retry_msgs = [system, *messages, ai, HumanMessage(content=_REMINDER)]
            ai = await llm.complete(messages=retry_msgs, tools=TOOL_SPECS)
            if ai.tool_calls and not _has_reasoning(ai):
                await emitter.emit_error("Reasoning missing after retry")
                return {
                    "messages": [ai],
                    "status": "failed",
                    "error_code": ErrorCode.REASONING_MISSING,
                    "finished": True,
                }

        if _has_reasoning(ai):
            await emitter.emit_reasoning(_text(ai).strip())
        in_tok, out_tok = _usage(ai)
        return {
            "messages": [ai],
            "step": state.step + 1,
            "history": [StepRecord(step=state.step + 1, node="reason", input_tokens=in_tok, output_tokens=out_tok)],
            **nudge_delta,
        }

    return reason
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd backend && uv run pytest tests/agent/test_reason_node.py -v`
Expected: PASS — 2 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/agent/prompt.py backend/app/agent/nodes/reason.py backend/tests/agent/test_reason_node.py
git commit -m "feat(agent): reason node with think-before-act enforcement"
```

---

### Task 9: `act` node

**Files:**
- Create: `backend/app/agent/nodes/act.py`
- Test: `backend/tests/agent/test_act_node.py`

**Interfaces:**
- Consumes: `ToolDispatcher`, `BrowserSession`, `EventEmitter`, `TrajectoryStore`, `AgentState`.
- Produces: `build_act_node(dispatcher, session, emitter, store)` → async `act(state) -> dict`. Reads the last `AIMessage.tool_calls`, dispatches each via `ToolDispatcher`, collects `ToolMessage`s + merges state deltas (later deltas win; `agent_memory` deltas accumulate). Records a `StepRecord(node="act", action=last_action, result=last_result)` to `history` and to the `TrajectoryStore`. Returns `{"messages":[...ToolMessages], "history":[record], ...merged deltas}`.

- [ ] **Step 1: Write the failing test `backend/tests/agent/test_act_node.py`**

```python
from langchain_core.messages import AIMessage, ToolMessage
from app.agent.state import AgentState
from app.agent.nodes.act import build_act_node
from app.tools.dispatcher import ToolDispatcher
from app.events.emitter import EventEmitter
from app.events.sink import BufferSink
from app.telemetry.store import InMemoryTrajectoryStore
from tests.fakes.fake_browser import FakeBrowserSession


def _state_with_toolcall(name, args, id="1"):
    s = AgentState(task="t", thread_id="t1")
    s.messages = [AIMessage(content="acting", tool_calls=[{"name": name, "args": args, "id": id}])]
    return s


async def test_act_dispatches_click_and_records():
    sess = FakeBrowserSession()
    store = InMemoryTrajectoryStore()
    node = build_act_node(ToolDispatcher(), sess, EventEmitter(BufferSink()), store)
    delta = await node(_state_with_toolcall("Click", {"index": 3}))
    assert isinstance(delta["messages"][0], ToolMessage)
    assert sess.acts[0].name == "click" and sess.acts[0].args["index"] == 3
    assert delta["last_action"].name == "click"
    assert store.records["t1"][0].node == "act"


async def test_act_complete_sets_finished():
    node = build_act_node(ToolDispatcher(), FakeBrowserSession(), EventEmitter(BufferSink()), InMemoryTrajectoryStore())
    delta = await node(_state_with_toolcall("Complete", {"success": True, "reason": "done"}))
    assert delta["finished"] is True and delta["success"] is True and delta["reason"] == "done"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/agent/test_act_node.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.agent.nodes.act'`.

- [ ] **Step 3: Create `backend/app/agent/nodes/act.py`**

```python
from __future__ import annotations

from langchain_core.messages import AIMessage

from app.agent.state import AgentState
from app.browser.base import BrowserSession
from app.events.emitter import EventEmitter
from app.telemetry.records import StepRecord
from app.telemetry.store import TrajectoryStore
from app.tools.dispatcher import ToolDispatcher


def build_act_node(
    dispatcher: ToolDispatcher,
    session: BrowserSession,
    emitter: EventEmitter,
    store: TrajectoryStore,
):
    async def act(state: AgentState) -> dict:
        last = state.messages[-1]
        tool_calls = last.tool_calls if isinstance(last, AIMessage) else []

        tool_messages = []
        merged: dict = {}
        memory = dict(state.agent_memory)
        for tc in tool_calls:
            msg, delta = await dispatcher.dispatch(tc, state=state, session=session, emitter=emitter)
            tool_messages.append(msg)
            if "agent_memory" in delta:
                memory.update(delta.pop("agent_memory"))
            merged.update(delta)
        if memory != state.agent_memory:
            merged["agent_memory"] = memory

        record = StepRecord(
            step=state.step,
            node="act",
            action=merged.get("last_action"),
            result=merged.get("last_result"),
        )
        await store.save(state.thread_id, record)
        return {"messages": tool_messages, "history": [record], **merged}

    return act
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && uv run pytest tests/agent/test_act_node.py -v`
Expected: PASS — 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/nodes/act.py backend/tests/agent/test_act_node.py
git commit -m "feat(agent): act node dispatching tool calls via ToolDispatcher"
```

---

### Task 10: Routing + graph builder + composition root

**Files:**
- Create: `backend/app/agent/routing.py`, `backend/app/agent/graph.py`, `backend/app/config/container.py`
- Modify: `backend/app/config/settings.py` (add `max_steps: int = 25`)
- Test: `backend/tests/agent/test_routing.py`

**Interfaces:**
- Consumes: all nodes, `AgentState`, `ErrorCode`, `InMemorySaver`.
- Produces: `route_after_reason(state) -> Literal["act","reason","__end__"]`, `route_after_act(state) -> Literal["observe","__end__"]` (with terminal field-setting handled via a tiny `finalize` step); `build_graph(*, session, llm, emitter, store, max_steps)` → compiled graph; `build_default_app()` in `container.py` wiring fakes (used by tests/demo). Graph edges: `START→observe→reason→⟨route_after_reason⟩`; `act→⟨route_after_act⟩`; routed `reason` (nudge) loops to `reason`; `done` paths go through `finalize`→`END`.

- [ ] **Step 1: Write the failing test `backend/tests/agent/test_routing.py`**

```python
from langchain_core.messages import AIMessage, HumanMessage
from app.agent.state import AgentState
from app.agent.routing import route_after_reason, route_after_act
from app.telemetry.records import ErrorCode


def _s(**kw):
    return AgentState(task="t", thread_id="t1", **kw)


def test_route_to_act_when_tool_calls_present():
    s = _s(step=1)
    s.messages = [AIMessage(content="go", tool_calls=[{"name": "Click", "args": {"index": 1}, "id": "1"}])]
    assert route_after_reason(s) == "act"


def test_route_nudge_then_fail_no_action():
    s = _s(step=1)
    s.messages = [AIMessage(content="hmm", tool_calls=[])]
    assert route_after_reason(s) == "reason"            # first time: nudge
    s.nudge_count = 1
    assert route_after_reason(s) == "finalize"          # second time: give up


def test_route_max_steps_to_finalize():
    s = _s(step=99)
    s.messages = [AIMessage(content="go", tool_calls=[{"name": "Click", "args": {"index": 1}, "id": "1"}])]
    assert route_after_reason(s, max_steps=25) == "finalize"


def test_route_after_act_finished_vs_observe():
    assert route_after_act(_s(finished=True)) == "finalize"
    assert route_after_act(_s(finished=False)) == "observe"


def test_route_after_reason_failed_status_finalizes():
    s = _s(status="failed", error_code=ErrorCode.REASONING_MISSING, finished=True)
    s.messages = [AIMessage(content="", tool_calls=[])]
    assert route_after_reason(s) == "finalize"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/agent/test_routing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.agent.routing'`.

- [ ] **Step 3: Add `max_steps` to `backend/app/config/settings.py`**

Add this field inside the existing `Settings` class (after `openrouter_base_url`):

```python
    max_steps: int = 25
```

- [ ] **Step 4: Create `backend/app/agent/routing.py`**

```python
from __future__ import annotations

from langchain_core.messages import AIMessage

from app.agent.state import AgentState
from app.telemetry.records import ErrorCode

_DEFAULT_MAX_STEPS = 25


def route_after_reason(state: AgentState, max_steps: int = _DEFAULT_MAX_STEPS) -> str:
    if state.finished or state.status == "failed":
        return "finalize"
    if state.step >= max_steps:
        return "finalize"
    last = state.messages[-1] if state.messages else None
    if isinstance(last, AIMessage) and last.tool_calls:
        return "act"
    # no tool call: nudge once, then give up
    if state.nudge_count < 1:
        return "reason"
    return "finalize"


def route_after_act(state: AgentState) -> str:
    return "finalize" if state.finished else "observe"
```

- [ ] **Step 5: Create `backend/app/agent/graph.py`**

```python
from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agent.nodes.act import build_act_node
from app.agent.nodes.observe import build_observe_node
from app.agent.nodes.reason import build_reason_node
from app.agent.routing import route_after_act, route_after_reason
from app.agent.state import AgentState
from app.browser.base import BrowserSession
from app.events.emitter import EventEmitter
from app.llm.base import LLMClient
from app.telemetry.records import ErrorCode, StepRecord
from app.telemetry.store import TrajectoryStore
from app.tools.dispatcher import ToolDispatcher


def build_finalize_node(emitter: EventEmitter, max_steps: int):
    """Resolve terminal status/error in one place and emit the finalize event.

    A closure (not functools.partial): LangGraph may mis-detect a partial of a
    coroutine as a sync node and fail to await it.
    """

    async def finalize(state: AgentState) -> dict:
        if state.finished and state.status != "failed":
            delta = {"status": "done" if state.success else "failed", "success": state.success}
        elif state.status == "failed":
            delta = {}  # reason node already set status/error_code
        elif state.step >= max_steps:
            delta = {"status": "failed", "error_code": ErrorCode.MAX_STEPS}
        else:
            delta = {"status": "failed", "error_code": ErrorCode.NO_ACTION}
        await emitter.emit_finalize(bool(state.success), state.reason or str(delta.get("error_code", "")))
        return {**delta, "history": [StepRecord(step=state.step, node="finalize",
                                                error_code=delta.get("error_code"))]}

    return finalize


def build_graph(*, session: BrowserSession, llm: LLMClient, emitter: EventEmitter,
                store: TrajectoryStore, max_steps: int = 25):
    g = StateGraph(AgentState)
    g.add_node("observe", build_observe_node(session, emitter))
    g.add_node("reason", build_reason_node(llm, emitter))
    g.add_node("act", build_act_node(ToolDispatcher(), session, emitter, store))
    g.add_node("finalize", build_finalize_node(emitter, max_steps))

    g.add_edge(START, "observe")
    g.add_edge("observe", "reason")
    g.add_conditional_edges("reason", lambda s: route_after_reason(s, max_steps),
                            {"act": "act", "reason": "reason", "finalize": "finalize"})
    g.add_conditional_edges("act", route_after_act, {"observe": "observe", "finalize": "finalize"})
    g.add_edge("finalize", END)
    return g.compile(checkpointer=InMemorySaver())
```

- [ ] **Step 6: Create `backend/app/config/container.py`**

```python
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
```

- [ ] **Step 7: Run to verify it passes**

Run: `cd backend && uv run pytest tests/agent/test_routing.py -v`
Expected: PASS — 5 passed.

- [ ] **Step 8: Commit**

```bash
git add backend/app/agent/routing.py backend/app/agent/graph.py backend/app/config/container.py backend/app/config/settings.py backend/tests/agent/test_routing.py
git commit -m "feat(agent): routing, graph builder, composition root (fakes)"
```

---

### Task 11: End-to-end loop on fakes + demo

**Files:**
- Create: `backend/app/agent/demo.py`
- Test: `backend/tests/agent/test_loop_e2e.py`

**Interfaces:**
- Consumes: `build_default_app`, `FakeBrowserSession`, `FakeLLMClient`, `ai`, `AgentState`.
- Produces: `run(graph, task, thread_id="demo") -> AgentState` helper that `astream`s the graph and returns the final state; a `__main__` that runs a scripted demo and prints node updates.

- [ ] **Step 1: Write the failing test `backend/tests/agent/test_loop_e2e.py`**

```python
from browser_agent_contracts import Element, Observation, Viewport
from app.config.container import build_default_app
from app.agent.demo import run
from tests.fakes.fake_browser import FakeBrowserSession
from tests.fakes.fake_llm import FakeLLMClient, ai


def _obs(n_elements=1):
    return Observation(url="https://app", title="App", viewport=Viewport(width=1, height=1),
                       elements=[Element(index=1, role="button", name="Login")][:n_elements])


async def test_happy_path_reaches_done_via_complete():
    # turn 1: click; turn 2: complete
    llm = FakeLLMClient(turns=[
        ai("I'll click Login", [{"name": "Click", "args": {"index": 1}, "id": "a"}]),
        ai("Logged in; finishing", [{"name": "Complete", "args": {"success": True, "reason": "done"}, "id": "b"}]),
    ])
    sess = FakeBrowserSession(observations=[_obs(), _obs()])
    graph, emitter, store, sink = build_default_app(session=sess, llm=llm)
    final = await run(graph, task="log in", thread_id="t1")
    assert final.status == "done" and final.success is True and final.reason == "done"
    assert sess.acts[0].name == "click"
    assert any(e.type == "finalize" for e in sink.events)
    assert any(r.node == "act" for r in store.records["t1"])


async def test_remember_persists_in_state_across_turns():
    llm = FakeLLMClient(turns=[
        ai("Note the login url", [{"name": "Remember", "args": {"key": "url", "value": "/auth"}, "id": "a"}]),
        ai("Done", [{"name": "Complete", "args": {"success": True, "reason": "ok"}, "id": "b"}]),
    ])
    graph, *_ = build_default_app(session=FakeBrowserSession(), llm=llm)
    final = await run(graph, task="t", thread_id="t2")
    assert final.agent_memory == {"url": "/auth"}


async def test_no_tool_call_nudges_then_fails_no_action():
    llm = FakeLLMClient(turns=[ai("hmm no action", []), ai("still nothing", [])])
    graph, emitter, store, sink = build_default_app(session=FakeBrowserSession(), llm=llm)
    final = await run(graph, task="t", thread_id="t3")
    assert final.status == "failed" and final.error_code is not None
    assert final.error_code.value == "NO_ACTION"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/agent/test_loop_e2e.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.agent.demo'`.

- [ ] **Step 3: Create `backend/app/agent/demo.py`**

```python
from __future__ import annotations

import asyncio

from app.agent.state import AgentState


async def run(graph, task: str, thread_id: str = "demo") -> AgentState:
    """Astream the graph to completion; return the final AgentState.

    Input is a plain dict (the documented LangGraph input form) — the graph fills
    the AgentState defaults. `aget_state(config).values` is a dict we re-validate.
    """
    config = {"configurable": {"thread_id": thread_id}}
    async for _ in graph.astream(
        {"task": task, "thread_id": thread_id}, config=config, stream_mode="updates"
    ):
        pass
    snapshot = await graph.aget_state(config)
    return AgentState.model_validate(snapshot.values)


async def _demo() -> None:
    from app.config.container import build_default_app
    from tests.fakes.fake_browser import FakeBrowserSession
    from tests.fakes.fake_llm import FakeLLMClient, ai

    llm = FakeLLMClient(turns=[
        ai("I'll click Login", [{"name": "Click", "args": {"index": 1}, "id": "a"}]),
        ai("Done", [{"name": "Complete", "args": {"success": True, "reason": "done"}, "id": "b"}]),
    ])
    graph, emitter, store, sink = build_default_app(session=FakeBrowserSession(), llm=llm)
    final = await run(graph, task="log in (fake demo)", thread_id="demo")
    print(f"status={final.status} success={final.success} reason={final.reason!r}")
    for ev in sink.events:
        print(f"  · {ev.type}: {ev.data}")


if __name__ == "__main__":
    asyncio.run(_demo())
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && uv run pytest tests/agent/test_loop_e2e.py -v`
Expected: PASS — 3 passed.

- [ ] **Step 5: Run the demo for a human-visible sanity check**

Run: `cd backend && uv run python -m app.agent.demo`
Expected: prints `status=done success=True reason='done'` followed by a list of streamed events (reasoning, tool_call, observation, finalize).

- [ ] **Step 6: Run the full backend suite (no regressions)**

Run: `cd backend && uv run pytest -q`
Expected: all tests pass (Phase A `test_health` + all `tests/agent/*` + `tests/fakes` usage), output pristine.

- [ ] **Step 7: Commit**

```bash
git add backend/app/agent/demo.py backend/tests/agent/test_loop_e2e.py
git commit -m "feat(agent): end-to-end ReAct loop on fakes + runnable demo"
```

---

## Self-Review

**Spec coverage (design spec §6 loop & state, §7.1 tools, §7.4 events, telemetry, §8 testing):**
- §6.1 loop `observe→reason→act→route` + explicit `complete()` + nudge/max-steps → Tasks 7–11. ✓
- §6.2 `AgentState` (Pydantic, `add_messages`, history) → Task 2. ✓
- §6.3 thin nodes delegating to ports + think-before-act (`REASONING_MISSING`) → Tasks 7–9. ✓
- §7.1 tools (registry/specs + descriptions + browser→ActionCall + memory/control) → Tasks 4–5. ✓
- §7.4 events (protocol + emitter + sink port) → Tasks 1, 3. ✓
- Telemetry `StepRecord`/`ErrorCode`/in-mem `TrajectoryStore` → Task 1. ✓
- §8 graph tests on fakes: happy→done, NO_ACTION nudge, REASONING_MISSING, tool→ActionCall, events, StepRecords → Tasks 8, 9, 11. ✓
- **Deferred (B2–B4, correctly out of scope):** real OpenRouter LLMClient + Jinja2 prompts + metering/streaming (B2); LocalCDPSession + funnel + ACTION_TIMEOUT enforcement (B3); MEMORY.md persistence + async writer + compaction (B4). `agent_memory` is in-RAM only here.

**Placeholder scan:** No "TBD/handle errors/etc." — every step has concrete code + commands. ✓

**Type consistency:** `AgentState` field names, `StepRecord`, `ErrorCode` members, `ToolDispatcher.dispatch(...)->(ToolMessage, dict)`, tool-spec class names (`Click`/`TypeText`/`Complete`...), the `_BROWSER_ACTION` name→ActionCall map, node builder signatures (`build_observe_node(session, emitter)`, `build_reason_node(llm, emitter)`, `build_act_node(dispatcher, session, emitter, store)`), routing return keys (`"act"/"reason"/"observe"/"finalize"`) and the graph's conditional-edge maps are consistent across Tasks 1–11. ✓

**Note for the implementer:** `route_after_reason` returns `"finalize"` (a real node) rather than `END` so terminal status/`error_code` get resolved in one place (`_finalize`); the graph maps every terminal route to the `finalize` node, then `finalize→END`.
