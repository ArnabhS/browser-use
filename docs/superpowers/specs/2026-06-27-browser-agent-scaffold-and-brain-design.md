# Design — Browser Agent (Web): Monorepo Scaffold + The Brain

- **Date:** 2026-06-27
- **Status:** Draft — pending user review
- **Source contract:** `.idea/CLAUDE-browser-agent-web.md` (to be promoted to root `CLAUDE.md`)
- **Relates:** this is the first build milestone; later milestones referenced in §9.

---

## 1. Context & goal

Build a standalone, web-based browser-use agent. The agent reasons in the cloud (a FastAPI +
LangGraph backend — "the brain"), talks to LLMs through **OpenRouter** (OpenAI-compatible, via
LangChain behind a port), and will ultimately drive the user's own Chrome through a browser
extension. The full architecture is fixed by the source contract; this spec covers the **first two
phases**: laying out the monorepo structure for every unit, then building the agent loop wired to
real OpenRouter.

## 2. Scope

**Phase A — Scaffold the structure (all units):**

- Lay out `backend/`, `frontend/`, `bridge-extension/`, `packages/contracts/`, `docs/`.
- Each unit gets its base config only (pyproject / package.json / manifest / vite config) — enough
  to install and build, no feature logic for FE/extension yet.
- Stand up the **contracts source of truth** (Pydantic v2 → JSON Schema → Zod) — this is real, not a
  stub, because the brain imports it.
- Root tooling: `pnpm-workspace.yaml`, `justfile`, `.gitignore`, `.env.example`, promote the source
  contract to root `CLAUDE.md`.

**Phase B — Build the main browser agent (backend brain):**

- `AgentState` + LangGraph `StateGraph`: `observe → plan → act → observe → verify → ⟨router⟩`.
- Ports (`Protocol`s): `LLMClient`, `BrowserSession`, `TrajectoryStore`.
- Services (one job each): `Planner`, `Executor`, `Validator`, `ActionDispatcher`.
- **Real OpenRouter `LLMClient`** impl (`langchain_openai.ChatOpenAI`, `base_url` =
  `https://openrouter.ai/api/v1`), behind the port — graph/services never see LangChain types.
- Telemetry: `StepRecord`, `ErrorCode`, an in-memory `TrajectoryStore`; meter every LLM call
  (tokens, cost, latency, cache).
- Composition root (`config/container.py`) — the only place wiring concretes.
- Checkpointer = `MemorySaver` (dev).

**Out of scope for this milestone (YAGNI — later milestones):**

- Real browser control (`LocalCDPSession` / CDP / the Python observation funnel) — the brain is
  built **fake-first** against a scripted `FakeBrowserSession`; real local Chrome is the very next
  milestone (§8, M2).
- The extension's real funnel + `chrome.debugger` dispatch + WS relay (M4).
- The real cockpit UX; FE stays a scaffolded shell (M3).
- WS authentication, Postgres/SQLite persistence, contract-drift CI gate beyond a local `just`
  target (added with M2/M3).

## 3. Decisions log

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Monorepo, all 4 units laid out up front | User chose structure-first. |
| 2 | Scaffold structure → then build the brain | User's explicit sequence. |
| 3 | Contracts: **Pydantic-first** (Python authors truth → emit JSON Schema → generate Zod/TS) | Backend is the authority; Pydantic v2 → JSON Schema is lossless and first-class. |
| 4 | Brain built **fake-first** for `BrowserSession`, real for `LLMClient` | Spec mandates TDD with fakes for the browser; OpenRouter key is available, so the LLM is real from day one. |
| 5 | Real OpenRouter wired now (key ready) | Read from `OPENROUTER_API_KEY` via gitignored `.env`; server-side only. |
| 6 | Models per role from env config | `PLANNER_MODEL` / `EXECUTOR_MODEL` / `VALIDATOR_MODEL`; never hardcoded. |

## 4. Repo layout (at the existing root)

```
browser-use/
├─ backend/
│  ├─ app/
│  │  ├─ agent/       # state.py, graph.py, nodes.py, router.py
│  │  ├─ planner/     # Planner port + impl
│  │  ├─ executor/    # Executor: prompt build + action parse (think-before-act)
│  │  ├─ validator/   # Validator + Contract/Visual/Rubric layers (Contract layer now)
│  │  ├─ actions/     # ActionCall types (from contracts) + ActionDispatcher contract
│  │  ├─ observation/ # Observation model (from contracts); server funnel arrives in M2
│  │  ├─ browser/     # BrowserSession port; FakeBrowserSession now, LocalCDP/ExtensionBridge later
│  │  ├─ llm/         # LLMClient port + OpenRouter impl + metering
│  │  ├─ telemetry/   # StepRecord, ErrorCode, TrajectoryStore (in-memory)
│  │  ├─ api/         # FastAPI app + /health (WS hub arrives with the cockpit, M3)
│  │  └─ config/      # settings + composition root
│  ├─ tests/          # pytest; fakes for BrowserSession + LLMClient
│  └─ pyproject.toml  # uv; path-deps on packages/contracts (python)
├─ frontend/          # Vite + React + TS + Tailwind + TanStack + Zod — scaffold only
├─ bridge-extension/  # MV3 + Vite — scaffold only
├─ packages/contracts/
│  ├─ src_py/         # authored Pydantic v2 models (the truth) + PROTOCOL_VERSION
│  ├─ schema/         # committed *.schema.json (emitted)
│  ├─ src/generated/  # generated Zod + TS (consumed by FE + extension)
│  └─ scripts/        # gen.py (emit JSON Schema) + zod generation
├─ pnpm-workspace.yaml
├─ justfile           # setup · gen-contracts · dev · test · check
├─ .env.example
├─ docs/
└─ CLAUDE.md          # promoted source contract
```

## 5. Contracts pipeline (Pydantic-first)

- **Author** `Observation`, `ActionCall`, `ActionResult`, and an `Envelope`
  (`{protocolVersion, type, payload}`) as Pydantic v2 in `packages/contracts/src_py/`. A
  `PROTOCOL_VERSION` constant lives here.
- `Observation` carries **no coordinates and no raw DOM**:
  `{protocolVersion, url, title, viewport, elements:[{index, role, name, value?}], screenshotRef,
  changed?, droppedCount?}`. `ActionCall` ≈ `{name, args}` referencing elements by `index`.
- **`just gen-contracts`** → `gen.py` emits `schema/*.schema.json` via `model_json_schema()` →
  `json-schema-to-zod` writes `src/generated/*.ts` → builds the `@browser-agent/contracts` package.
- **Backend** takes a `uv` path dependency on `src_py/` and imports contract models directly; it
  never redefines wire types. `observation/` and `actions/` wrap them with server-only logic.
- A `just check` target regenerates and runs `git diff --exit-code` to catch drift locally (the CI
  gate is added in a later milestone).

## 6. The brain (Phase B) — architecture

### 6.1 State

`AgentState` (TypedDict) exactly per the contract: `task`, `observation`, `plan`, `history`
(`Annotated[list[StepRecord], add]`), `last_action`, `last_result`, `status`, `error_code`, `turn`.

### 6.2 Nodes (thin closures over injected services)

| Node | Calls | Writes |
|------|-------|--------|
| `observe` | `BrowserSession.observe()` | fresh `observation` (rebuilt every turn) |
| `plan` | `Planner.plan/revise(...)` | `plan` |
| `act` | `Executor` → `ActionDispatcher` → `BrowserSession.act()` | `last_action`, `last_result` |
| `verify` | `Validator` (Contract layer now; Visual/Rubric later) | `status`, maybe `error_code` |

Nodes contain **no** LLM/CDP/DB code inline — they delegate to injected ports/services (SOLID §6 of
the contract). Indices are never reused across turns.

### 6.3 Edges & routing

`START → observe → plan → act → observe → verify → ⟨router⟩`;
`add_conditional_edges("verify", route, {done: END, continue: act, replan: plan, fail: END})`.
Action-level errors route `act → observe` for **one** retry, then escalate to `fail` with a typed
`ErrorCode`. No human-in-the-loop failure fallback.

### 6.4 Ports (Protocols; injected at the composition root)

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

### 6.5 OpenRouter `LLMClient` impl

`langchain_openai.ChatOpenAI(base_url="https://openrouter.ai/api/v1",
api_key=settings.openrouter_api_key, model=<role model>)`, wrapped to satisfy `LLMClient` and return
an `LLMResult` carrying content + `usage` (tokens/cache) + measured latency. Rules from the contract:
keys server-side only; model per role from config; **meter every call** (planner + validator too);
retry transient 429/5xx with backoff respecting `Retry-After`, **never re-routing models in a
retry**; sanitize secrets/PII from logs; executor prompt requires a `## Reasoning` section
(think-before-act) — reject empty/trivial reasoning, retry once, else fail `REASONING_MISSING`.

### 6.6 Telemetry

`StepRecord` (node/turn, action, result, error_code, tokens, cost, cache, latency); `ErrorCode`
enum (`ACTION_TIMEOUT`, `REASONING_MISSING`, …); in-memory `TrajectoryStore` now (DB later).

## 7. Testing strategy (TDD, red→green per unit)

- **Contracts:** Pydantic round-trip; emitted schema matches committed `schema/*.json`; a vitest test
  parses a sample with the generated Zod.
- **Brain (pytest, fakes for both ports):** feed a scripted `Observation` + canned LLM response,
  assert the routed path (`done` / `continue` / `replan` / `fail`) and the emitted `StepRecord`s.
  Cover: happy path to `done`; action-error → one retry → `fail` with `ErrorCode`; missing-reasoning
  → `REASONING_MISSING`; metering populated on every LLM call.
- **OpenRouter impl:** unit-tested with a stubbed transport (no live network in CI); one optional
  live smoke test gated behind the real key.

## 8. Acceptance criteria

- `just setup` installs backend (uv) + JS workspace (pnpm).
- `just gen-contracts` produces `schema/*.json` + `src/generated/*.ts`; `just check` is clean.
- `uv run pytest` is green: the graph drives a fake run to `done`, emits metered `StepRecord`s, and
  exercises the retry/fail and missing-reasoning paths.
- With a real key in `.env`, a `run_demo` script astreams a run using the **real** OpenRouter
  `LLMClient` against the **fake** `BrowserSession` and reaches a terminal status, printing streamed
  node updates.
- FE + extension folders install/build as empty scaffolds.

## 9. Later milestones (context, not this spec)

- **M2 — Real eyes:** `LocalCDPSession` (headless Chrome over CDP) + the Python observation funnel
  (Extract→Visibility→Occlusion→WrapperCollapse→SoMIndexer→ReadingOrder); swap the fake
  `BrowserSession` for the real one with **zero graph changes**. Adaptive settle wait.
- **M3 — Cockpit:** FastAPI WS hub + the React cockpit (live screenshots, reasoning stream, run
  controls, take-over via LangGraph `interrupt`).
- **M4 — Extension:** TS funnel stages + `chrome.debugger` trusted-input dispatch + authenticated WS
  relay; `ExtensionBridgeSession` drives the user's real Chrome.
