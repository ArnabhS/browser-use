# CLAUDE.md — Browser Agent (Web)

> A standalone, web-based browser-use agent. The agent reasons in the cloud, drives the
> **user's own Chrome** through a browser extension, talks to LLMs through **OpenRouter**, and
> is orchestrated as a **LangGraph** state machine. This is a clean rewrite — same proven
> concepts as the prior "okkotsu" engine, but decoupled from any desktop/Electron host and
> standardized on LangGraph (the prior engine may use LlamaIndex; **do not** port LlamaIndex
> agent constructs — translate them into LangGraph nodes/edges).

This file is the contract for how to build and work in this repo. Read it before writing code.

---

## 1. What this is

A browser automation agent exposed as a web app. A user types a task ("log into X and download
last month's invoice"), and the agent perceives the page, decides an action, performs it in the
user's real browser, and repeats until the task is verified done — streaming every step to a live
cockpit UI.

**Three deployable units, one repo (monorepo):**

```
┌─────────────────────┐    REST + WebSocket     ┌────────────────────────────┐
│ frontend (React)     │ ◄─────────────────────► │ backend (FastAPI + LangGraph)│
│ cockpit: task input, │                          │ THE BRAIN — runs the agent  │
│ live screenshots,    │                          │ graph: observe·plan·act·    │
│ step log, run control│                          │ verify · OpenRouter · store │
└─────────────────────┘                          └─────────────▲──────────────┘
                                                                │ authenticated WS relay
                                                                │ (compact Observation / ActionCall — NOT raw DOM)
                                                  ┌─────────────▼──────────────┐
                                                  │ bridge-extension (TypeScript)│
                                                  │ runs in user's Chrome tab:   │
                                                  │ observation FUNNEL +         │
                                                  │ trusted input dispatch       │
                                                  │ via chrome.debugger (CDP)    │
                                                  └─────────────────────────────┘
```

### The load-bearing split (do not violate)

- **The agent loop runs in the backend.** Per-turn latency is dominated by the LLM call
  (seconds), not by relaying input over the network (milliseconds). Keeping the loop server-side
  keeps the **OpenRouter key, all reasoning, and all trajectories** off the user's machine.
- **The observation funnel runs in the extension**, next to the DOM. It prunes the page down to a
  small numbered element list **before** anything crosses the network. **The raw DOM never leaves
  the user's browser.**
- **The two sides agree on only two contracts:** the `Observation` schema and the `ActionCall`
  schema (Pydantic on the backend ↔ Zod in the extension/frontend, generated from one source of
  truth — see §8).

---

## 2. The core idea you must internalize

A real web page's DOM is enormous (100k–500k+ tokens of divs, scripts, inline styles). **You never
send the DOM to the LLM.** The whole system is a funnel that throws away ~99% of the page and hands
the model a short, numbered list of only the things it can act on or read.

**Mental model — restaurant:**
- The **kitchen** (raw DOM tree) is huge and messy; the model never goes in there.
- The **menu** (flat numbered element list) is short and clean; that's all the LLM reads.
- The **waiter** (the engine) knows "#5 on the menu" = "the button at coordinate (400, 330)" and
  performs it.

The LLM picks a **number**. It never navigates a tree and never sees a coordinate. The extension
keeps the hidden `index → geometry` map and turns "click 5" into a trusted input event.

---

## 3. The agent loop — LangGraph

The orchestration is a `langgraph.graph.StateGraph`. **Nodes are thin.** They call injected
services and return a state delta; they contain **no** LLM/CDP/DB code inline (see SOLID, §6).

### State

```python
class AgentState(TypedDict):
    task: str
    observation: Observation | None        # compact, indexed — from the extension funnel
    plan: Plan | None
    history: Annotated[list[StepRecord], add]  # telemetry per node/turn
    last_action: ActionCall | None
    last_result: ActionResult | None
    status: Literal["running", "done", "failed"]
    error_code: ErrorCode | None
    turn: int
```

### Nodes (each delegates to an injected service)

| Node | Calls | Returns into state |
|------|-------|--------------------|
| `observe` | `BrowserSession.observe()` | fresh `observation` (rebuilt every turn — indices are **not** stable across turns) |
| `plan` | `Planner.plan/revise(...)` | `plan` (initial, or revised on replan) |
| `act` | `Executor` → `ActionDispatcher` → `BrowserSession.act()` | `last_action`, `last_result` |
| `verify` | `Validator` (contract / visual / rubric layers) | `status`, maybe `error_code` |

### Edges

```
START → observe → plan → act → observe → verify → ⟨router⟩
router: done → END ·  continue → act ·  replan → plan ·  fail → END
```

- `add_conditional_edges("verify", route, {...})` reads `status`/`error_code`.
- Action-level errors (timeout, occluded target) route from `act` back to `observe` for one retry,
  then escalate to `fail` with a typed `ErrorCode`. **No human-in-the-loop fallback for failures —
  fail with a typed code.**

### Checkpointer = persistence + pause/resume + take-over

- Compile with a checkpointer (`MemorySaver` in dev; a SQLite/Postgres saver in prod).
- `thread_id` == one browser session. This gives trajectory persistence and resume for free.
- **Human take-over:** use a LangGraph `interrupt` so the user can grab their own browser mid-run;
  resume with `Command(resume=...)`. This is natural here because it's *their* browser.

### Streaming to the cockpit

Drive the run with `graph.astream(..., stream_mode="updates")` (or `astream_events`) and forward
each node update over the WebSocket hub to the frontend — task progress, screenshots, reasoning,
and the chosen action appear live.

### Do NOT

- Do not call `ChatOpenAI`/OpenRouter or CDP directly inside a node. Nodes call **ports** (§6).
- Do not keep mutable agent state outside `AgentState` — the graph state is the single source.
- Do not reuse element indices from a previous turn — always act on the freshest `observation`.

---

## 4. Observation funnel (in the extension)

Runs in the user's Chrome via a content script + `chrome.debugger`. Stages, in order — **each stage
is one class with one transform** (SRP), composed into a pipeline (OCP: add a stage = add a class):

1. **Extract** — DOM + accessibility roles/names + layout geometry (boxes) + a screenshot.
2. **VisibilityFilter** — drop `display:none`, `visibility:hidden`, `opacity:0`, zero-size,
   off-screen.
3. **OcclusionCuller** — drop elements physically covered by something else (e.g. content behind an
   open modal), using geometry + hit-testing.
4. **WrapperCollapser** — collapse pure layout wrappers (`div>div>div>button` → `button`).
5. **SoMIndexer** (Set-of-Marks) — assign each interactable a small integer `[N]`; build the hidden
   `index → {backendNodeId, centerX, centerY}` map (kept in the extension).
6. **ReadingOrderFormatter** — serialize survivors to a compact list in visual reading order;
   truncate long text; cap repeated list items; emit a `## Current Focus` line from the AX focus.

**Output = the `Observation` contract** (§8): the numbered list + a screenshot ref + scroll/viewport
hints + a `changed` summary. Typical size after the funnel: **~1–3k tokens** vs 100k+ raw.

**Guardrails:**
- The raw DOM/snapshot must **never** be sent to the backend — send only the funnel output.
- Enforce a hard token budget on the serialized list; when over budget, drop lowest priority
  (off-screen, non-interactive) first **and log what was dropped** ("18 offscreen items hidden") so
  the agent scrolls instead of assuming it saw everything. Silent truncation = confidently wrong.
- **Change detection:** after an action, prefer sending a diff ("dialog appeared", "navigated to
  /x") plus the new list, not a blind full dump.

---

## 5. Actions (dispatched in the extension)

Element targeting is by **SoM index**, resolved to coordinates via the hidden map, then performed as
**trusted input** through `chrome.debugger` (CDP `Input.*`) — `isTrusted: true`, so hover/synthetic
event systems and anti-bot checks behave like a real user. Never use JS `element.click()` as the
default (untrusted, `isTrusted:false`, skips hover) — only as an explicit fallback.

Action vocabulary (each = one dispatcher handler implementing the `Action` interface; per-action
timeout wall):

| Action | CDP / mechanism | Default timeout |
|--------|-----------------|-----------------|
| `navigate` | `Page.navigate` | 30s |
| `click` | `Input.dispatchMouseEvent` press+release @ (x,y) | 10s |
| `type` | `Input.dispatchKeyEvent` per char / `Input.insertText` | 10s |
| `clear` | select-all + delete | 5s |
| `select_option` | set value + dispatch change | 10s |
| `scroll` | `Input.dispatchMouseEvent` mouseWheel | 5s |
| `wait_for` | poll condition/element | 30s |
| `extract` | read region text/attrs on demand | 15s |
| `new_tab` / `switch_tab` / `close_tab` | `Target.*` | 10/5/5s |

Each returns `ActionResult{ success, reason, error_code? }`. On timeout → `ACTION_TIMEOUT`.

**Handling change after an action (popup / navigation / new tab):** the engine does **not** track
it. After every action it **waits for the page to settle, then re-observes from scratch** (the
`act → observe` edge). A popup just appears in the next fresh list (and occlusion culling hides
what's behind it, so the modal becomes the salient thing). A full navigation re-observes the new
page. A new window is a new CDP target reachable via the tab actions.

**Settle / stability wait:** before re-observing, wait for the page to go quiet — network idle, DOM
mutations stop, load/navigation events fired. Use an **adaptive per-host bound** (learn how long a
site typically takes; wait ~`mean + 2·stddev`, clamped to [min, max]) so fast sites stay snappy and
animation-heavy sites don't get read half-rendered.

---

## 6. SOLID — enforced, not aspirational

This codebase is organized so the LangGraph nodes and the composition root are the only places that
know about concrete implementations. Everything else depends on narrow interfaces (ports).

- **S — Single Responsibility.** One job per module: each funnel stage, each action handler, each of
  `Planner` / `Executor` / `Validator` / `ActionDispatcher` / `LLMClient` / `TrajectoryStore`. If a
  file grows past ~300 lines or you can't name its one job, split it.
- **O — Open/Closed.** Add a funnel stage, an action, or a validator layer by adding a class that
  implements the relevant interface. The pipeline, dispatcher, and validator composer **do not
  change**.
- **L — Liskov.** Every `BrowserSession` impl and every `Stage`/`Action`/`VerificationLayer` is
  drop-in swappable. Tests use fakes that satisfy the same contract.
- **I — Interface Segregation.** Ports are narrow: `LLMClient.complete()`, `BrowserSession.observe()
  / act() / navigate()`, `TrajectoryStore.save()`. No consumer depends on methods it doesn't call.
- **D — Dependency Inversion.** The graph and services depend on **abstractions**; concretes
  (OpenRouter, the extension bridge, the DB) are constructed in **one composition root**
  (`config/container`) and injected. Nodes are closures/partials over injected services.

### Key ports (define these as Protocols/ABCs; inject impls)

```python
class LLMClient(Protocol):
    async def complete(self, *, role: str, messages, model: str) -> LLMResult: ...

class BrowserSession(Protocol):
    async def observe(self, *, include_som: bool = True) -> Observation: ...
    async def act(self, call: ActionCall) -> ActionResult: ...
    async def navigate(self, url: str) -> ActionResult: ...
    async def tabs(self) -> list[TabInfo]: ...

class TrajectoryStore(Protocol):
    async def save(self, thread_id: str, record: StepRecord) -> None: ...
```

`BrowserSession` has two impls, swappable with zero graph changes:
- `ExtensionBridgeSession` — **default**; relays coarse `observe()/act()` calls over the
  authenticated WS to the user's extension.
- `LocalCDPSession` — dev/CI; drives a local headless Chrome directly over CDP (no extension).

---

## 7. LLM via OpenRouter

OpenRouter is the only LLM gateway. It is OpenAI-compatible, so the default `LLMClient` impl can use
`langchain_openai.ChatOpenAI(base_url="https://openrouter.ai/api/v1", api_key=..., model=...)` **or**
a thin `httpx` client — but the graph/services only ever see the `LLMClient` port, never LangChain
or OpenRouter types.

**Rules:**
- **Keys are server-side only.** Never ship the OpenRouter key to the extension or frontend.
- **Model per role.** `planner`, `executor`, and `validator` each read their model slug from config
  (env/settings). Don't hardcode model IDs in code — they're configuration.
- **Meter every call.** Extract `usage` (prompt/completion tokens, cached tokens) + measured latency
  and write a `StepRecord` (cost, tokens, cache, latency) per LLM call — including planner and
  validator calls, not just executor.
- **Retry with backoff** on transient 429/5xx (respect `Retry-After`). **Never re-route to a
  different model inside a retry** — the user chose the model; a retry uses the same one.
- **Sanitize** secrets/PII out of logs, trajectory artifacts, and error reasons.
- **Think-before-act:** the executor prompt must require a `## Reasoning` section before any action;
  reject empty/trivial reasoning and retry once, else fail with `REASONING_MISSING`.

---

## 8. Boundary contracts (single source of truth)

`Observation` and `ActionCall` are the only things the backend and the extension/frontend share.
Define them **once** and generate both sides:

- Author the schema once (e.g. Pydantic models → export JSON Schema; generate Zod/TS types from it,
  or vice-versa). CI fails if the generated types drift.
- **Version the wire protocol.** Every message carries a `protocolVersion`; the bridge and backend
  reject mismatches with a clear error.
- `Observation` ≈ `{ protocolVersion, url, title, viewport, elements: [{index, role, name, value?}],
  screenshotRef, changed?, droppedCount? }`. It carries **no coordinates** (those stay in the
  extension's hidden map) and **no raw DOM**.
- `ActionCall` ≈ `{ name, args }` referencing elements by `index`.

---

## 9. Repo layout

```
browser-agent-web/                 # rename to taste
├─ backend/
│  ├─ app/
│  │  ├─ agent/          # LangGraph: graph build, nodes, routers, state
│  │  ├─ planner/        # Planner service (port + impl)
│  │  ├─ executor/       # Executor: prompt build, CodeAct/action parse
│  │  ├─ validator/      # Validator + Contract/Visual/Rubric layers
│  │  ├─ actions/        # ActionCall types + dispatcher contract
│  │  ├─ observation/    # Observation model + (server-side) funnel for LocalCDPSession
│  │  ├─ browser/        # BrowserSession port; ExtensionBridgeSession, LocalCDPSession
│  │  ├─ llm/            # LLMClient port + OpenRouter impl + metering
│  │  ├─ telemetry/      # StepRecord, ErrorCode, TrajectoryStore
│  │  ├─ api/            # FastAPI routes + WebSocket hub (UI side + bridge side)
│  │  └─ config/         # settings + composition root (the only place wiring concretes)
│  ├─ tests/             # pytest; fakes for BrowserSession + LLMClient
│  └─ pyproject.toml
├─ bridge-extension/     # TS Chrome extension: funnel stages + chrome.debugger dispatch + WS client
├─ frontend/            # React + Vite + TanStack Query/Router + Tailwind + Zod (cockpit)
├─ packages/contracts/  # shared Observation/ActionCall schema → generated Pydantic + Zod
├─ docs/
└─ CLAUDE.md            # this file
```

---

## 10. Tech stack

- **Backend:** Python 3.12+, FastAPI, **LangGraph** (orchestration) + LangChain core (LLM plumbing
  behind the `LLMClient` port), `httpx`, Pydantic v2, `websockets`. Async throughout.
- **LLM:** OpenRouter (OpenAI-compatible), via `langchain_openai.ChatOpenAI` or `httpx`.
- **Extension:** TypeScript, `chrome.debugger` (CDP), Manifest V3, a WS client to the backend.
- **Frontend:** React 18, Vite, TanStack Router + Query, Tailwind, Zod, framer-motion.
- **Persistence:** LangGraph checkpointer (SQLite dev / Postgres prod) + `TrajectoryStore`.

---

## 11. Dev workflow & commands

- **TDD is the workflow.** Red → green → refactor. Write the failing test first.
  - Unit-test each funnel stage and each action handler in isolation.
  - Test the graph with **fakes** for `BrowserSession` and `LLMClient` (no real browser/LLM): feed a
    scripted observation + canned LLM response, assert the routed path and emitted `StepRecord`s.
  - Integration-test the loop end-to-end against `LocalCDPSession` + a headless Chrome on a fixture
    page.
- **Backend:** `cd backend && uv sync && uv run uvicorn app.api.main:app --reload`; tests:
  `uv run pytest`.
- **Extension:** `cd bridge-extension && pnpm i && pnpm build`; load unpacked in Chrome; tests:
  `pnpm test`.
- **Frontend:** `cd frontend && pnpm i && pnpm dev`; tests: `pnpm test`.
- **Contracts:** regenerate after any schema change; CI fails on drift between Pydantic and Zod.

---

## 12. Guardrails — do NOT

- ❌ No Electron/desktop dependencies anywhere. This is a web app.
- ❌ No business/agent logic in the `api/` layer — it only adapts HTTP/WS to services.
- ❌ No OpenRouter or CDP calls inside LangGraph nodes — go through ports.
- ❌ No raw DOM/snapshot over the wire — only funnel output.
- ❌ No OpenRouter key outside the backend.
- ❌ No model re-routing inside a retry; no silent model substitution.
- ❌ No reuse of previous-turn element indices; re-observe and rebuild every turn.
- ❌ No human-in-the-loop *failure* fallback — fail with a typed `ErrorCode`. (HIL is allowed only as
  an explicit user "take over my browser" interrupt.)
- ❌ No silent truncation of the observation — always log dropped/hidden counts.

---

## 13. Glossary

- **CDP** — Chrome DevTools Protocol; the JSON-RPC-over-WebSocket API used to inspect/control Chrome.
  Reached here via the extension's `chrome.debugger`.
- **Observation funnel** — the staged pipeline that prunes the raw DOM to a compact numbered list.
- **SoM (Set-of-Marks)** — overlaying a small integer index on each interactable so the LLM can
  reference elements by number instead of selector/coordinates.
- **Trusted input** — synthetic events with `isTrusted: true` (via CDP `Input.*`), indistinguishable
  from a real user; the default for clicks/typing.
- **Settle / stability wait** — waiting for the page to go quiet (network/DOM/load) before
  re-observing, bounded adaptively per host.
- **Trajectory** — the ordered list of `StepRecord`s for a run (cost, tokens, latency, action,
  result, error_code); persisted via the checkpointer + `TrajectoryStore`.
