# Design — Browser Agent (Web): Monorepo Scaffold + The Brain

- **Date:** 2026-06-27
- **Status:** Draft — pending user review
- **Source contract:** `.idea/CLAUDE-browser-agent-web.md` (to be promoted to root `CLAUDE.md`)
- **Reference codebases studied** (ports/adaptations, not dependencies):
  - **Mahoraga** (`/Users/arnabh/work/mahoraga/mahoraga-mac/mahoraga/mahoraga/agent`) — a mobile
    ReAct agent. We take its **agent-loop shape** (stateful, re-perceive-each-turn) and its
    **async non-blocking write** pattern (`asyncio.Queue` + background worker).
  - **test_gen_agent** (`/Users/arnabh/work/mahoraga/mahoraga-mac/test-gen-agent/test_gen_agent`) — a
    LangGraph tool-calling agent. We take its **tool-calling action mechanism**, **event
    emitter/protocol**, **MEMORY.md memory document**, **decomposed Jinja2 prompts**, **ToolRegistry**
    organization, **compaction**, and **OpenRouter `ChatOpenAI` + metering** patterns.
- **Relates:** first build milestone; later milestones referenced in §11.

---

## 1. Context & goal

A standalone, web-based browser-use agent. The agent reasons in the cloud (a FastAPI + **LangGraph**
backend — "the brain"), talks to LLMs through **OpenRouter** (OpenAI-compatible, via LangChain behind
a port), and will ultimately drive the user's own Chrome through a browser extension. This spec
covers the first two phases: laying out the monorepo for every unit, then building the agent loop.

**The brain is a tool-calling ReAct loop** modeled on Mahoraga's *shape* but using **structured
tool-calls** (not code execution) for actions — see §3 decision 7 and §10 for the rationale.

## 2. Scope

**Phase A — Scaffold the structure (all units):** lay out `backend/`, `frontend/`,
`bridge-extension/`, `packages/contracts/`, `docs/`; each unit gets base config only (no FE/extension
feature logic); stand up the **contracts source of truth** (Pydantic v2 → JSON Schema → Zod); root
tooling (`pnpm-workspace.yaml`, `justfile`, `.env.example`); promote the source contract to root
`CLAUDE.md`.

**Phase B — Build the main browser agent (backend brain), driving a real browser:** a LangGraph
tool-calling ReAct loop — `observe → reason → act → (re-observe) → …` — terminating on an explicit
`complete()` tool. Built against a **real `LocalCDPSession`** (Playwright shell + CDP core) driving
local headless Chrome, with the **real Python observation funnel**; the OpenRouter `LLMClient` is real
too. `FakeBrowserSession` is kept **only as a unit-test double** (never on the real path). Includes the
five borrowed subsystems — **tools** (registry + structured browser/memory/control tools), **memory**
(MEMORY.md + async writer), **prompts** (decomposed Jinja2), **events** (emitter + protocol + sink),
**metering/compaction** — **plus the real eyes**: `LocalCDPSession` + the observation funnel (§7.6).

**Out of scope this milestone (YAGNI — later milestones):**

- The extension's funnel + `chrome.debugger` dispatch + WS relay — M3 (the extension milestone).
- Real cockpit UX; FE stays a scaffolded shell — M2 (the cockpit milestone).
- WS auth, Postgres/SQLite persistence, contract-drift CI beyond a local `just` target.
- **Code-execution / sandbox** — explicitly rejected for actions (§10); a hard-sandboxed `run_python`
  escape tool is a possible *future* addition only if a real need appears.
- Compaction **layer 2** (LLM-summarize) — ships as a fast-follow; Phase B ships layers 0–1.

## 3. Decisions log

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Monorepo, all 4 units laid out up front | User chose structure-first. |
| 2 | Scaffold structure → then build the brain | User's explicit sequence. |
| 3 | Contracts **Pydantic-first** (Python authors truth → JSON Schema → Zod) | Backend is authority; lossless. |
| 4 | Brain built against a **real `LocalCDPSession`** from the start (old "M2 real eyes" absorbed into Phase B); `FakeBrowserSession` kept **only as a unit-test double** | User wants real browser control in Phase B; real OpenRouter `LLMClient` (key available). |
| 5 | Real OpenRouter now (key ready) | `OPENROUTER_API_KEY` via gitignored `.env`, server-side only. |
| 6 | Models from env config (not hardcoded) | Single-agent loop ⇒ one primary `AGENT_MODEL` (the `reason` node); room for `SUMMARIZER_MODEL` (compaction layer 2) and a future `VALIDATOR_MODEL`. |
| 7 | **Actions = structured tool-calls, NOT code execution** | Adversarial web ⇒ code-exec risks RCE via prompt injection; index-staleness weakens code-exec's composition benefit; tool-calls are schema-validated, safer, observable. Re-aligns with the spec's `ActionCall{name,args}`. See §10. |
| 8 | Keep Mahoraga's **loop shape** (`observe→reason→act→re-observe`) | The *environment* is stateful/pushed (a live page), independent of action mechanism. |
| 9 | Explicit **`complete(success, reason)`** terminal tool (not "no tool_calls = done") | Disambiguates "finished" vs "stuck"; matches typed-completion/fail philosophy. |
| 10 | State = Pydantic `BaseModel` (was TypedDict) + `messages: Annotated[list, add_messages]` | Validation; matches test_gen_agent. |
| 11 | **Memory = MEMORY.md document** (`## Knowledge` + `## Run History`) + in-RAM `agent_memory` mirror; **async non-blocking** writer | test_gen_agent's model + Mahoraga's queue+worker write pattern. |
| 12 | `remember(key, value)` structured (not freeform string) | Parseable Knowledge section. |
| 13 | Borrow test_gen's **events / decomposed Jinja2 prompts / ToolRegistry / compaction / metering** | Proven patterns in this exact stack (LangGraph + OpenRouter). |
| 14 | Browser via **Playwright shell + CDP core** | Playwright owns launch / bundled Chromium / targets / nav / screenshot; raw CDP via `cdp_session` for `DOMSnapshot` (geometry), `Accessibility.getFullAXTree`, and `Input.*` (trusted, `isTrusted:true`). Node-hop overhead ~0.5%/turn (LLM-dominated) — negligible. A thin `CdpClient` seam keeps Playwright-vs-raw swappable. |

## 4. Repo layout (at the existing root)

```
browser-use/
├─ backend/
│  ├─ app/
│  │  ├─ agent/        # state.py, graph.py, routing.py, nodes/{observe,reason,act}.py
│  │  ├─ tools/        # registry.py, signature.py; browser/{click,type,navigate,scroll,extract,wait_for,tabs}.py;
│  │  │                #   memory/{remember,recall}.py; control/{complete,set_plan}.py
│  │  ├─ prompt/       # loader.py (Jinja2 Env), resolver.py (custom overrides)
│  │  ├─ prompts/      # agent/{system,identity,policy,context,tools,output-format}.jinja2; skills/*.jinja2
│  │  ├─ memory/       # document.py (build/parse/update_knowledge/append_run), store.py (port), async_markdown.py
│  │  ├─ events/       # protocol.py (AgentEvent + types), emitter.py (EventEmitter), sink.py (EventSink port)
│  │  ├─ browser/      # BrowserSession port; LocalCDPSession (Playwright+CDP); cdp_client.py (CDP seam); FakeBrowserSession (test double)
│  │  ├─ observation/  # Observation model + funnel/{extract,visibility,occlusion,wrapper_collapse,som_indexer,reading_order}.py + pipeline.py + index_map.py
│  │  ├─ actions/      # ActionCall types (from contracts) + dispatch helper (tool → ActionCall → act())
│  │  ├─ llm/          # LLMClient port + OpenRouter impl (ChatOpenAI) + usage.py (UsageTracker)
│  │  ├─ telemetry/    # StepRecord, ErrorCode, TrajectoryStore (in-memory)
│  │  ├─ compaction.py # context-window management (layers 0–1 now, 2 fast-follow)
│  │  ├─ api/          # FastAPI app + /health (WS hub arrives with the cockpit, M3)
│  │  └─ config/       # settings.py + container.py (the only place wiring concretes)
│  ├─ tests/
│  └─ pyproject.toml   # uv; path-dep on packages/contracts (python)
├─ frontend/           # Vite + React + TS + Tailwind + TanStack + Zod — scaffold only
├─ bridge-extension/   # MV3 + Vite — scaffold only
├─ packages/contracts/ # src_py/ (Pydantic truth) · schema/ (*.json) · src/generated/ (Zod+TS) · scripts/
├─ pnpm-workspace.yaml · justfile · .env.example · docs/ · CLAUDE.md
```

## 5. Contracts pipeline (Pydantic-first)

- Author `Observation`, `ActionCall`, `ActionResult`, `Envelope` (`{protocolVersion, type, payload}`)
  + a `PROTOCOL_VERSION` constant as Pydantic v2 in `packages/contracts/src_py/`.
- `Observation` carries **no coordinates, no raw DOM**:
  `{protocolVersion, url, title, viewport, elements:[{index, role, name, value?}], screenshotRef,
  changed?, droppedCount?}`. `ActionCall` ≈ `{name, args}` referencing elements by `index`.
- `just gen-contracts` → `model_json_schema()` → `schema/*.json` → `json-schema-to-zod` →
  `src/generated/*.ts` → build `@browser-agent/contracts`. Backend takes a `uv` path-dep on `src_py/`.
- `just check` regenerates + `git diff --exit-code` (local drift guard; CI gate later).

## 6. The brain — loop & state

### 6.1 Loop (tool-calling ReAct, Mahoraga shape)

```
START → observe → reason → ⟨route_reason⟩
route_reason:  has tool_calls → act
               no tool_calls (first time) → reason  (nudge: "call a tool or complete()")
               no tool_calls (after nudge) → END(fail: NO_ACTION)
               step ≥ max_steps → END(fail: MAX_STEPS)
act → ⟨route_act⟩
route_act:     complete() was called → END(done | fail, per success)
               else → observe        (re-perceive: page changed)
```

- `reason` ≈ test_gen's `agent` node; `act` ≈ its `tools` node; `observe` is prepended because the
  environment is stateful/pushed. A read-only/memory-only action may skip the re-observe (later
  fast-path). Settle/stability wait lives at the tail of `act` before re-observe.

### 6.2 State (`AgentState`, Pydantic `BaseModel`)

`messages: Annotated[list[BaseMessage], add_messages]`, `task`, `observation: Observation | None`,
`agent_memory: dict[str, str]` (in-RAM Knowledge mirror), `memory_document: str` (loaded MEMORY.md),
`last_action: ActionCall | None`, `last_result: ActionResult | None`, `status: running|done|failed`,
`error_code: ErrorCode | None`, `step: int`, `finished/success/reason`, usage counters
(`last_input_tokens`, `total_output_tokens`). Graph state is the single source of truth.

### 6.3 Nodes (thin; delegate to injected services)

| Node | Does | Writes |
|------|------|--------|
| `observe` | `BrowserSession.observe()` → SoM element list + screenshot ref; inject as a device-state block | `observation` |
| `reason` | compaction check → render decomposed Jinja2 (+memory block +tool descriptions) → `LLMClient.complete` (tools bound, **streaming** to emitter) → enforce reasoning | `messages`(AIMessage), usage |
| `act` | dispatch each tool_call: browser tool → `ActionCall` → `BrowserSession.act()`; `remember`/`set_plan`/`complete`; settle wait; scan `remember()` → update `agent_memory` + **enqueue async MEMORY.md write** | `messages`(ToolMessages), `last_action/result`, `finished` |

`reason` enforces **think-before-act**: if reasoning is empty/trivial, retry once, else fail
`REASONING_MISSING`. Indices are never reused across turns (re-observe rebuilds them).

## 7. Subsystems (five borrowed + the real eyes)

### 7.1 Tools (test_gen `ToolRegistry`)

- `ToolSignature{name, args, description, factory, requires, inject}`; `ToolRegistry` filters by
  availability, instantiates with injected deps, and `get_tool_descriptions()` generates the
  `- name(args): desc` string rendered into the prompt. Tools bound via
  `llm.bind_tools(tools, parallel_tool_calls=True)`.
- **Read** tools (pure): `extract`, `wait_for`, (later) `get_state`. **Effect** tools: `click`,
  `type`, `clear`, `select_option`, `scroll`, `navigate`, `new_tab/switch_tab/close_tab`. **Memory**:
  `remember(key,value)`, `recall()`. **Control**: `complete(success,reason)`, `set_plan(steps)`.
- Each browser tool builds an `ActionCall(name,args)` (referencing `index`) → `BrowserSession.act()`
  → `ActionResult`. Per-action timeout walls per the source contract (`ACTION_TIMEOUT`).
- Effect/state-mutating tools return a confirmation string; the `act` node performs the state write
  (test_gen's pure-tool pattern).

### 7.2 Memory (test_gen MEMORY.md + Mahoraga async writer)

- **Document** (`memory/document.py`): one Markdown string — `## Knowledge` (`- **key**: value`) +
  `## Run History` (auto-compacted: last N verbatim, older digested), char budget. Helpers:
  `build_document`, `parse_knowledge`, `update_knowledge`, `append_run`.
- **Lifecycle:** on run start, load `memory.md` → `parse_knowledge` → `agent_memory`. The memory block
  is injected into every `reason` prompt. `remember(key,value)` updates `agent_memory` and the `act`
  node **enqueues** an async write; `append_run` at finalize. On checkpointer resume, rehydrate from
  the file.
- **`MemoryStore` port** + `AsyncMarkdownMemory` impl: `asyncio.Queue` + background worker writing
  `runs/{thread_id}/memory.md` via `aiofiles`; `append()` does `put_nowait` (**non-blocking**, drops
  with warning on full); `start()/stop(timeout)` lifecycle; failures logged, loop never crashes.

### 7.3 Prompts (test_gen decomposed Jinja2)

- `prompt/loader.py`: cached `Environment(trim_blocks, lstrip_blocks)`; `system.jinja2` composes
  partials via `{% include %}` — `identity` + `policy` + `skills/_index` + `context` + `tools` +
  `output-format`. `prompt/resolver.py` allows runtime custom-prompt overrides per key.
- Skills conditionally injected by flags (`{% if has_forms %}` etc.). Context dict carries
  `tool_descriptions`, `observation`, memory block, task, model_name, conditional flags.

### 7.4 Events (test_gen emitter + protocol + a sink port)

- `events/protocol.py`: `AgentEvent{event, data, ts}` + a typed vocabulary (`STATUS`, `COMMENTARY`/
  reasoning, `TOOL_CALL`, `OBSERVATION`, `STREAM`, `USAGE_UPDATE`, `CONTEXT_STATUS`, `COMPACT_SUMMARY`,
  `PLAN_UPDATE`, `MEMORY_UPDATE`, `ERROR`, `FINALIZE`).
- `events/emitter.py`: `EventEmitter` (thread-safe, one method per type). It writes to an **`EventSink`
  port** (`events/sink.py`) — a buffer/log sink in Phase B, swapped to the WS hub in M3. The graph
  drives `astream(stream_mode="updates")` and the emitter forwards node updates.

### 7.5 LLM/OpenRouter + metering + compaction

- `llm/openrouter.py`: `ChatOpenAI(base_url="https://openrouter.ai/api/v1",
  api_key=settings.openrouter_api_key, model=<role>, stream_usage=True)` behind `LLMClient`; `astream`
  → `emit_stream`; returns `LLMResult` (content + tool_calls + usage + latency). Retry transient
  429/5xx with backoff (respect `Retry-After`), **never re-route models**; sanitize secrets/PII.
- `llm/usage.py` `UsageTracker`: per-call tokens (prompt/completion/cached) + OpenRouter cost
  pass-through → `StepRecord` + `emit_usage_update` on **every** LLM call (the agent call now; the
  compaction-summarizer / validator calls when added).
- `compaction.py`: trigger at ~95% of context window using real API `input_tokens`. **Layer 0**
  strip old screenshots/observations once "seen"; **Layer 1** truncate old tool outputs;
  **Layer 2** (fast-follow) LLM-summarize older messages, keep first-2 + last-6 verbatim, emit
  `compact_summary`. Emit `context_status` each turn.

### 7.6 Real eyes — `LocalCDPSession` + observation funnel (from the source contract)

- **`LocalCDPSession`** (`browser/`) implements the `BrowserSession` port over **Playwright**
  (async API): launches bundled headless Chromium, manages targets/tabs, navigation, and screenshots.
  A thin **`CdpClient`** seam wraps `page.context.new_cdp_session(page)` so the funnel's `Extract`
  stage and the action dispatch speak **raw CDP** for the fidelity/perf-critical calls —
  `DOMSnapshot.captureSnapshot` (nodes + computed styles + layout boxes/geometry),
  `Accessibility.getFullAXTree` (roles/names), `Page.captureScreenshot`, and `Input.dispatchMouseEvent`
  / `Input.dispatchKeyEvent` (trusted, `isTrusted:true`). Keeping CDP behind `CdpClient` makes the
  Playwright-vs-raw choice swappable without touching the funnel.
- **Observation funnel** (`observation/funnel/`) — composable stages (SRP/OCP, each one class with one
  transform), per source-contract §4, run as a pipeline producing the `Observation` contract:
  `Extract` (CDP snapshot+AX+geometry+screenshot) → `VisibilityFilter` → `OcclusionCuller` →
  `WrapperCollapser` → `SoMIndexer` (assigns `[N]`; builds the **hidden `index → {centerX, centerY,
  backendNodeId}` map** kept server-side) → `ReadingOrderFormatter` (compact list in reading order).
  Enforce a token budget; **log dropped/hidden counts** (no silent truncation).
- **Action dispatch:** a tool's `ActionCall` resolves `index → geometry` via the SoM map, then
  performs trusted input through `CdpClient` (`Input.*`). Per-action timeout walls (`ACTION_TIMEOUT`).
  After acting, settle/stability wait (start: fixed bound; adaptive per-host is a fast-follow), then
  re-observe (fresh indices).
- **Incremental delivery:** the pipeline carries all six stage slots from day one (OCP), but lands in
  order of value — `Extract` + `VisibilityFilter` + `SoMIndexer` + `ReadingOrderFormatter` first (a
  correct, usable observation), then `OcclusionCuller` + `WrapperCollapser` as quality fast-follows.

## 8. Testing strategy (TDD, red→green per unit)

- **Contracts:** Pydantic round-trip; emitted schema matches committed `schema/*.json`; vitest parses a
  sample with generated Zod.
- **Memory document:** `build/parse/update_knowledge/append_run` round-trip; budget truncation; async
  writer is non-blocking (enqueue returns immediately) and drains on `stop()`.
- **Tools:** each tool builds the right `ActionCall`; registry generates correct descriptions; effect
  tools mutate state via the node; `complete()` sets terminal state.
- **Funnel stages (unit, synthetic CDP-snapshot fixtures):** each stage in isolation — visibility
  drops hidden/zero-size/off-screen; occlusion culls covered nodes; wrapper-collapse flattens layout
  divs; `SoMIndexer` assigns stable-within-turn `[N]` and builds the geometry map; reading-order
  serialization respects the token budget and **logs dropped/hidden counts**.
- **Graph (pytest, `FakeBrowserSession` + fake `LLMClient`):** the fast/hermetic path — scripted
  `Observation` + canned tool-call → assert routed path (`act`/`reason`-nudge/`END`) and emitted
  `StepRecord`s. Cover: happy path to `done` via `complete()`; `NO_ACTION` after a nudge;
  `REASONING_MISSING`; action error → retry → `fail`; metering populated each LLM call.
- **Integration (real headless Chrome, local fixtures):** full funnel + trusted-input dispatch via
  `LocalCDPSession` against **local static HTML fixtures** (served by the test / `file://` — never
  live sites): assert the funnel yields the expected element list and a scripted task drives to
  `complete()`. Marked slow; excluded from the fast unit run.
- **OpenRouter impl:** stubbed transport (no live network in CI); one optional live smoke test gated
  on the real key.

## 9. Acceptance criteria

- `just setup` installs backend (uv, incl. `playwright install chromium`) + JS workspace (pnpm);
  `just gen-contracts` + `just check` clean.
- `uv run pytest` green: contracts, memory, tools, funnel stages, and the graph (on fakes) — the fast
  hermetic suite.
- With a real key in `.env`, a `run_demo` `astream`s a run using the **real** OpenRouter `LLMClient`
  (tools bound) against the **real `LocalCDPSession`** on a **local fixture page** in headless Chrome:
  the funnel produces a numbered `Observation`, the agent clicks/types via trusted CDP input, reaches
  a terminal status via `complete()`, streams node/token/usage events, and writes a `memory.md`.
- FE + extension folders install/build as empty scaffolds.

## 10. Why tool-calls, not code execution (rationale)

For an **adversarial-web** agent the benefit/cost of code-exec inverts: page content enters the LLM
context, so prompt injection on CodeAct escalates to **arbitrary backend RCE** (sandbox escapes are a
perennial class); meanwhile code-exec's in-turn composition benefit is **weakened** because SoM
indices go stale the moment the page mutates (the spec mandates re-observe-and-rebuild each turn).
Tool-calls are schema-validated, safer, observable, and map 1:1 onto the spec's `ActionCall`. We
recover lost composition via richer tools (`extract`, `scroll_until`, `wait_for`) and parallel tool
calls. Industry precedent (browser-use, computer-use, Operator) is structured actions, not code-exec.

## 11. Later milestones (context, not this spec)

- **M2 — Cockpit:** FastAPI WS hub + `EventSink`→WS; React cockpit (live screenshots, reasoning/token
  stream, plan, run controls, take-over via LangGraph `interrupt`).
- **M3 — Extension:** TS funnel stages + `chrome.debugger` trusted-input dispatch + authenticated WS
  relay; `ExtensionBridgeSession` drives the user's real Chrome — swapped in for `LocalCDPSession`
  with **zero graph changes** (the SOLID payoff). Fast-follows from Phase B that land here or alongside:
  adaptive per-host settle, compaction layer 2.
```
