# P0 adoptions from browser-use OSS — design

**Date:** 2026-07-03
**Status:** Draft for review
**Related:** `browser-use-oss-comparison` (memory), the architecture teardown artifact, `browser-agent-roadmap`.

## Scope of THIS spec (Track A)

This spec now covers **only the three browser-layer-independent P0s** — P0-1 caching, P0-2 `*`-new
marker, P0-3 evaluation. They ship on the current code and are unaffected by the direction change
below.

## Direction change (2026-07-03) — bridge out, raw CDP in

The user decided: **(1) drop the bridge extension from active consideration for now**, and **(2)
replace Playwright with raw CDP as the sole browser driver.** Consequences held consciously:

- The **privacy split is paused** — with no bridge, we launch Chrome server-side and extract the DOM
  there, so raw DOM lives on the server. (Intended to be temporary; the bridge can layer back on the
  same `BrowserSession` port later.)
- The **datacenter-IP anti-bot gap returns** — server-side CDP means a datacenter IP, so hard
  bot-walls (Skyscanner/PerimeterX) again need `BROWSER_PROXY` (residential); headful-under-xvfb
  alone won't clear them.

This splits the work into two tracks:

- **Track A (this spec):** P0-1, P0-2, P0-3 — browser-independent, ship now.
- **Track B (`2026-07-03-cdp-foundation-design.md`):** the Playwright→raw-CDP switch, and the two
  browser-dependent P0s built on it — **P0-4 `search_page`/`find_elements`** and **P0-5 extensions**
  (trivial under CDP: a `--load-extension` flag).

The two tracks are independent and can proceed in parallel; Track A does not wait on Track B.

## Workflow

TDD throughout (CLAUDE.md §11): red → green → refactor, one test-first per unit. Contract changes
regenerate Pydantic → JSON Schema → Zod and must not drift (`just gen-contracts` / `just check`).

---

## P0-1 · OpenRouter prompt caching  *(isolated cost win — do first)*

**What:** cache the stable system-prompt + tool-schema prefix on every turn so we pay full input
price once per ~5-min window instead of every step. Cached tokens bill at 0.25×.

**Mechanism (verified):** Anthropic models via OpenRouter are **not** auto-cached. Add
`cache_control: {"type": "ephemeral"}` to the **last content block of the system message**; Anthropic
caches the longest prefix up to that breakpoint, which includes the bound tool definitions (they sit
before the system block in Anthropic's ordering). Limits: ≤4 breakpoints, ≥1024 tokens for Sonnet 4.6.
Usage returns `prompt_tokens_details.cached_tokens` + `cache_write_tokens`.

**The catch — a dynamic tail busts the cache.** `build_system_message` currently interpolates
`memory` (grows when the agent calls `Remember`) and `task` (run-constant) into the system prompt.
Memory must move OUT of the cached block.

**Design:**
- Split `build_system_message` output into: **(a)** stable instructions — `identity` + `policy` +
  `context` + `tools` + `output-format` + the run-constant `task` — emitted as a `SystemMessage`
  whose content is a block list with `cache_control: ephemeral` on the final block; **(b)** the
  dynamic `agent_memory`, rendered as a separate short message appended after the system block (or
  folded into the per-turn observation message). `task` stays in the cached prefix (constant per run).
- In `OpenRouterLLMClient` / the `ChatOpenAI` binding, ensure the content-block `cache_control` key
  is forwarded to OpenRouter. **Verification task:** a live run must show `cached_tokens > 0` on
  turn ≥2; if LangChain strips the key, fall back to `additional_kwargs` / `extra_body`.
- Surface `cached_tokens` in `UsageTracker` metering + a cockpit line so cache hits are visible.

**Tests:** unit — the built system message carries exactly one ephemeral breakpoint on its last
block and memory is not inside it; unit — memory changes do not change the cached-prefix bytes.
Live smoke — `cached_tokens > 0` on the second turn (manual, documented).

**Files:** `app/agent/prompt.py`, `app/agent/nodes/reason.py` (message assembly), `app/llm/openrouter.py`,
`app/llm/usage.py`.

---

## P0-2 · `*`-new-element marker  *(contract + observe)*

**What:** prefix elements that appeared since the last action with `*`, so the model knows its click
opened the dropdown/modal/autocomplete. Highest-leverage fix for form/popup flows (the quashbugs /
HubSpot class of bug).

**We already have the machinery.** `observe.py::_signature` already builds per-element
`(role, name)` signatures to detect an unchanged page for stuck-detection. Reuse it for a per-element
diff.

**Design:**
- Contract: add `isNew: bool = False` to `Element` (regenerate Zod). No coordinates, no new PII.
- `observe` node: when a previous observation exists **and the URL is unchanged**, compute
  `prev_sigs = {(e.role, e.name, e.value) for e in prev.elements}`; stamp `isNew = sig not in prev_sigs`
  on each current element (via `model_copy`). On navigation (URL change) nothing is "new". Diffing in
  the **node**, not the funnel, keeps it independent of which `BrowserSession` impl produced the
  `Observation` — so it survives the browser-layer switch untouched.
- `format_observation`: render `*[N] role "name"` for new elements + a one-line legend
  (`* = appeared since your last action`).
- Prompt: one line in `policy`/`output-format` explaining the marker.

**Tests:** unit — element present last turn → not new; element absent last turn → new; URL change →
nothing new; empty previous → nothing new. Unit — `format_observation` renders `*` only for `isNew`.

**Files:** `packages/contracts/*` (Element), `app/agent/nodes/observe.py`, `app/agent/format.py`,
`app/prompts/agent/*.jinja2`.

---

## P0-3 · Strengthen `evaluation_previous_goal`  *(builds on P0-2)*

**What:** force the model to explicitly judge whether its last action achieved its goal, every turn,
as a first-class emitted signal — cheap grounding that pre-empts most of what `stuck_count` catches
only after the fact.

**Already half-built.** `output-format.jinja2` already says "Assess: what did your last action do".
The gap: it isn't required/parsed, isn't emitted distinctly to the cockpit, and lacks good evidence.

**Design:**
- Tighten `output-format.jinja2`: require the reasoning to **open** with a one-line assessment of the
  previous action, cross-checking the new observation (now including `*`-new elements from P0-2) and
  the last tool result. Skip on step 1 (no previous action).
- Emit the assessment as its own cockpit event (parse the first labelled line;
  `emitter.emit_evaluation`, or a structured `emit_reasoning`). Keep parsing minimal and tolerant.
- No schema/tool change — stays within our existing free-text-reasoning + think-before-act pattern
  (avoids a heavier structured-preamble tool; that's a P1 if we adopt multi-action).

**Tests:** unit — assessment line is parsed and emitted as a distinct `evaluation` event; unit — a
missing assessment neither retries nor emits; unit — first turn emits nothing.

**Refinement during implementation:** the assessment is **not** retry-enforced. A full LLM re-call to
nudge a formatting label would double per-step cost whenever the model omits it (and broke every
multi-turn e2e fake by exhausting its scripted turns). The prompt requirement + the emitted signal
carry the grounding value, and stuck-detection already catches no-effect actions. Only truly missing
*reasoning* still fails (`REASONING_MISSING`, unchanged).

**Files:** `app/prompts/agent/output-format.jinja2`, `app/agent/nodes/reason.py`, `app/events/emitter.py`.

---

## P0-4 · `search_page` + `find_elements`  →  moved to Track B

Now lives in `2026-07-03-cdp-foundation-design.md`. With the bridge out there is a single browser
path, so the extension-side handlers vanish and these become two small `Runtime.evaluate` branches on
the new CDP session — cleaner to build directly on that foundation than to write on Playwright and
redo.

## P0-5 · Auto-load reliability extensions  →  moved to Track B

Now lives in `2026-07-03-cdp-foundation-design.md`. Under raw CDP this is a `--load-extension` launch
flag rather than a Playwright persistent-context rewrite — cheap and low-risk, so it rejoins the
browser work rather than being deferred.

---

## Build order (Track A)

1. **P0-1 OpenRouter caching** — isolated, immediate cost win, touches only prompt/llm.
2. **P0-2 `*`-new marker** — contract + observe; unblocks P0-3.
3. **P0-3 evaluation_previous_goal** — depends on P0-2 for evidence.

Track B (CDP foundation + P0-4 + P0-5) proceeds under its own spec, in parallel.

## Out of scope (this spec)

- The Playwright→raw-CDP switch and P0-4/P0-5 — Track B (`2026-07-03-cdp-foundation-design.md`).
- All P1s (multi-action-per-step, `extract`-as-markdown-LLM, AX-tree fusion, `<secret>` creds + TOTP,
  JS-dialog auto-accept + allowed_domains) — a follow-up batch.
- Re-introducing the bridge extension (paused, not removed — the `BrowserSession` port stays, so it
  slots back later).

## Guardrail check

Track A touches no CLAUDE.md guardrails: no model re-routing, no index reuse (the `*`-marker diffs
signatures, not reused indices), OpenRouter caching keeps the key server-side. The "no raw DOM over
the wire" guardrail is a **bridge** invariant; with the bridge paused and extraction server-side, it
is inapplicable this batch — to be restored when the bridge returns (tracked in Track B's spec).
