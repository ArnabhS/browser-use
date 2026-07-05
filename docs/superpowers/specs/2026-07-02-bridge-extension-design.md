# Bridge Extension + Run Survival — Design (Milestone 1)

**Date:** 2026-07-02
**Status:** Approved design, pre-implementation
**Scope:** Milestone 1 only (split into 1a + 1b below). M2+ follow-ups are listed but out of scope.

---

## 1. Why

The agent currently drives a headless Chromium launched **server-side** on Hugging Face
(`LocalCDPSession`). Because that browser runs in a US datacenter, every site geolocates the run to
the US — no locale/timezone/geo override or (unreliable, quickly-blocked) proxy fixes it for sites
that geolocate by IP (Amazon.in, Google, "deliver to…").

The real fix is the architecture CLAUDE.md was designed around: drive **the user's own Chrome**. When
the browser runs on the user's machine, every site sees the user's **real residential IP** (Indian,
for an Indian user) and the user's **real logins/cookies** — for free, reliably, forever. That is the
`ExtensionBridgeSession` path: the backend brain relays coarse `observe()`/`act()` calls over a
WebSocket to a Chrome extension that funnels the DOM and dispatches trusted input via
`chrome.debugger`.

Separately, a live bug: **refreshing the cockpit kills the running task.** The run is owned by the
cockpit WebSocket, so a disconnect cancels it and tears down the browser. That is fixed here too, and
it turns out to be the natural foundation the bridge plugs into.

## 2. Goal, acceptance & milestones

This spec is one implementation unit split into two milestones that land in order:

- **Milestone 1b — Run survival (lands FIRST).** Decouple the run's lifecycle from the cockpit
  socket via a `RunManager`, so a cockpit refresh detaches the *view* without killing the *run*.
  Independent of the extension — it fixes the refresh bug on the **current** `LocalCDPSession`
  deployment immediately, and becomes the foundation 1a plugs into.
- **Milestone 1a — Bridge walking skeleton.** Prove the whole extension pipe end-to-end with a
  *minimal* funnel and *minimal* action set, running one real task on the user's Chrome.

**M1a acceptance (manual):** load the unpacked extension, click it to attach the active tab, start a
task (e.g. *"go to google, search 'browser use', click the first result"*) from the cockpit against a
**local** backend (`browser_backend=extension_bridge`), and watch it run in the user's own Chrome to
completion with a low-fps live view.

**M1b acceptance:** start a run, refresh the cockpit mid-run, and the UI re-attaches to the same
still-running task (with replayed history) instead of losing it.

**Non-goals (M1):** full-fidelity funnel (occlusion culling, wrapper collapse, AX-tree, adaptive
settle); authentication; multi-user/multi-session pairing; public (HF) deployment of the bridge;
offscreen-document lifecycle; human take-over interrupt.

## 3. What already exists (do not rebuild)

- **Contracts** (`packages/contracts/`): `Observation`, `Element`, `Viewport`, `Tab`, `ActionCall`,
  `ActionResult`, `Envelope` — as JSON Schema → generated **TS** (`src/generated/`) and **Python**
  (`src_py/browser_agent_contracts/`). `PROTOCOL_VERSION = "1.0.0"`.
- **`BrowserSession` port** (`backend/app/browser/base.py`): `observe / act / navigate / tabs`.
- **`LocalCDPSession`** fully implements the port (kept as dev/fallback — **coexists**, not replaced).
- **Live-view path**: `frame` event on the emitter, canvas renderer in the cockpit.
- **`ws.py`**: today owns the run bound to the cockpit socket and cancels it on disconnect (the bug).
- **Extension scaffold** (`bridge-extension/`): `public/manifest.json` + an empty
  `src/background/index.ts`, Vite build, depends on `@browser-agent/contracts`.

## 4. Topology

```
cockpit (/ws/run) ──attach/detach──►  RunManager ──owns──► run_task + browser session
   (ephemeral view, reconnectable)        │                        │
                                          │                        │  observe()/act()
                                          │                        ▼
                                          │            ExtensionBridgeSession  (M1a)
                                          │                        │  request/response (id)
                                          ▼                        ▼
                                   event buffer (replay)   NEW /ws/bridge ◄── extension SW
                                                                              (user's Chrome via
                                                                               chrome.debugger)
```

The run and the browser live in the `RunManager`, independent of any cockpit socket. With
`extension_bridge`, the browser is the user's Chrome owned by the *separate* `/ws/bridge` connection —
so a cockpit refresh cannot touch it at all. The only things crossing the bridge wire are
`Observation` / `ActionCall` / `ActionResult` (the CLAUDE.md §8 boundary). **Coordinates and raw DOM
never leave the extension.**

## 5. Run survival across cockpit reconnect (Milestone 1b)

**`RunManager`** — a process-level registry keyed by `thread_id`. Each entry owns the `run_task`, the
browser session/cleanup, a **bounded event buffer** (ring of recent events), and the
**currently-attached sink** (0 or 1 cockpit socket).

- **Start:** cockpit sends `start` with a client-persisted `thread_id`. `RunManager` creates the run,
  stores it, attaches the sink. Every event is **buffered *and* forwarded** to the attached sink.
- **Disconnect:** on `WebSocketDisconnect`, **detach the sink only** — do **not** cancel, do **not**
  tear down the browser. The run keeps running.
- **Reconnect:** cockpit reconnects and sends `attach` with the same `thread_id`. `RunManager`
  **replays the buffered events** to catch the UI up, then attaches the new sink for live events. If
  the run already finished while disconnected, it replays the tail + completion.
- **GC:** a run is torn down on explicit `stop`, or when it reaches a terminal state **and** stays
  with no attached sink past a short TTL (so an abandoned run can't leak a browser forever).

**Emitter indirection:** the emitter targets the `RunManager` entry (buffer + current sink), not a
fixed socket. `WebSocketSink` becomes "attach a socket to a run"; the run fans out to the attached
socket if any.

**Frontend:** persist `thread_id` in `localStorage` on start; on load, if there's a stored active
run, connect and send `attach` (resume) instead of showing idle; reconcile the UI from replayed
events; clear the stored id on completion/stop. Composes with the existing wake/retry.

## 6. Relay protocol (`/ws/bridge`, Milestone 1a)

**One contract change:** add an optional `id: str | None` to `Envelope` (regenerate TS + Python; keep
CI drift-check green). Optional, so existing UI-side `frame`/event envelopes are unaffected. Every
request carries an `id`; its response echoes the same `id`.

**Message types:**

| Direction | `type` | `payload` | Purpose |
|-----------|--------|-----------|---------|
| ext → backend | `register` | `{ userAgent, tabId }` | on connect: "I'm the browser, attached to a tab" |
| backend → ext | `observe` | `{ includeSom: bool }` | request an `Observation` |
| backend → ext | `act` | `ActionCall` | perform an action |
| backend → ext | `navigate` | `{ url }` | go to URL |
| backend → ext | `tabs` | `{}` | list tabs |
| ext → backend | `result` | `Observation` \| `ActionResult` \| `{ tabs: Tab[] }` | reply, echoes request `id` |
| ext → backend | `error` | `{ message, errorCode }` | request failed, echoes `id` |
| ext → backend | `frame` | `{ data, meta }` | live-view JPEG (unsolicited, no `id`) |

**`ExtensionBridgeSession` correlation:**
- Holds `pending: dict[id → asyncio.Future]`.
- `observe()` → new `id`, register future, send `{type:"observe", id, payload:{includeSom}}`, `await`
  with timeout, parse payload → `Observation`. Same shape for `act` / `navigate` / `tabs`.
- Inbound `result`/`error` → resolve/reject `pending[id]`. Inbound `frame` → forward to emitter.
  Inbound `register` → mark the bridge ready.
- **Timeout** (no response in N s): actions → `ActionResult(success=False, error_code="BRIDGE_TIMEOUT")`;
  observe → raise, so the graph fails with a typed code rather than hanging.

**Bridge hub (single-user, no-auth):** a module-level registry holds the *one* currently-connected
extension socket; `ExtensionBridgeSession` sends through it. If a run starts with **no** bridge
connected, fail immediately with a clear message. Cockpit shows a "browser connected / not connected"
status derived from the hub.

## 7. Extension internals (Milestone 1a)

**Structure (all in the MV3 service worker for M1), each a small SRP module:**
- **WS client** → `/ws/bridge`; routes inbound requests by `type`; sends `result`/`error`/`frame`.
- **`chrome.debugger` session** → attached to one tab; all CDP via `chrome.debugger.sendCommand`.
- **Funnel** (observe) and **Dispatcher** (act) — mirrors the backend's SRP split so M2 grows them
  without touching the WS glue.

**Attachment UX:** user clicks the toolbar icon → "Control this tab" → SW calls
`chrome.debugger.attach({tabId}, "1.3")` on the active tab and sends `register`. Chrome shows its
"extension is debugging this browser" banner (unavoidable with `chrome.debugger`; a good honesty
signal). Detaching / closing the banner ends the session.

**MV3 lifecycle — the one real risk.** The service worker is evicted after ~30s idle, which would
kill the WS. **M1 mitigation:** a **20s heartbeat ping** over the WS. Since Chrome 116, WebSocket
activity resets the SW idle timer, so an active heartbeat + in-flight requests keep it alive.
**Hardening path (M2, documented not built):** move the WS + funnel into an **offscreen document**
(longer lifecycle) if eviction still bites.

**Minimal funnel (M1):** one `Runtime.evaluate` runs a collector *in the page* returning visible
interactables (`a, button, input, select, textarea, [role=button], [onclick]`, …) filtered by
`getBoundingClientRect` visibility, each with `{role, name, value, centerX, centerY}`. The SW numbers
them `[0..N]`, keeps the hidden `index → {x,y}` map, and emits an `Observation` (elements carry **no**
coordinates). Screenshot via `Page.captureScreenshot` (jpeg q50) → sent as a `frame`. **Raw DOM stays
in the page.**

**Minimal dispatch (M1):**
- `navigate` → `Page.navigate`, wait for `load`.
- `click` → map index→(x,y); `Input.dispatchMouseEvent` press+release (trusted, `isTrusted:true`).
- `type` → `Input.insertText` into the focused field (after a click).
- `scroll` → `Input.dispatchMouseEvent` `mouseWheel` with `deltaY`.
- Settle: wait for `load` after navigate; a short fixed pause after click/type.

`extract` / `done` / `answer` stay agent-side (not browser actions), unchanged. After every action the
graph re-observes (`act → observe` edge); the extension does not track change itself.

## 8. Error handling (typed codes, never hang)

| Situation | Handling |
|-----------|----------|
| Run starts, no bridge connected | Immediate typed failure + cockpit message. No silent hang. |
| Bridge disconnects mid-run (SW evicted / tab closed / banner cancelled) | Pending futures reject → `ActionResult(error_code="BRIDGE_DISCONNECTED")` → graph fails typed. |
| Request times out (no `result` in N s) | `BRIDGE_TIMEOUT` → typed fail. |
| CDP command fails in extension (bad URL, target gone) | Dispatcher catches → `error` w/ code (`NAV_FAILED`/`ACTION_TIMEOUT`) → action-level error routes `act → observe` for one retry, then escalate. |
| Screenshot capture fails | Best-effort: skip the frame, run continues (live view degrades). |
| Cockpit disconnects (refresh) | **Not an error** — detach sink, run continues (§5). |

## 9. Testing (each half tested without the other)

**Milestone 1b:**
- **`RunManager`** — unit tests: start registers a run; disconnect detaches sink without cancelling
  the `run_task`; reconnect replays buffered events then attaches; terminal + no-sink + TTL → GC;
  explicit `stop` tears down immediately.
- **`/ws/run` reconnect** — integration test via FastAPI `TestClient`: start a scripted run, drop the
  socket, reconnect with the same `thread_id`, assert replayed history + live continuation.

**Milestone 1a:**
- **Backend `ExtensionBridgeSession`** — unit tests with a **fake bridge socket** (captures outbound
  envelopes, feeds back canned `result`/`error`): `observe()` sends `{type:"observe", id}` and returns
  the parsed `Observation`; `act()` correlates the `id`; timeout → `BRIDGE_TIMEOUT`; inbound `frame`
  → forwarded to emitter; no-bridge → clean typed failure. Because it satisfies the `BrowserSession`
  port, existing graph tests cover the loop unchanged.
- **`/ws/bridge` endpoint** — integration test via FastAPI `TestClient` websocket: fake extension
  connects, `register`s, a scripted-LLM run drives observe/act envelopes, results route back.
- **Extension funnel collector** — pure DOM→list logic, unit-tested in happy-dom against fixture HTML:
  visible collected, hidden dropped, `index→coord` map built, numbering stable within a turn.
- **Extension dispatcher** — unit test with a **fake `chrome.debugger`** (records `sendCommand`):
  click → correct coords + press/release, type → `insertText`, navigate → `Page.navigate`.
- **Extension WS router** — fake WebSocket: `observe`/`act` in → funnel/dispatcher called → `result`
  echoing the `id` out; bad type → `error`.
- **M1a acceptance (manual):** load unpacked, attach a tab, run a real Google search on the user's
  Chrome against the local backend.

## 10. Explicit follow-ups (NOT in M1)

- **Auth (next step before any public deployment):** shared `BRIDGE_TOKEN` — the extension's options
  page holds a secret matching a backend setting; `/ws/bridge` rejects mismatches. **Guardrail until
  then: run the extension against a LOCAL backend only, never the public HF URL** (an unauthenticated
  public bridge would let a stranger burn the OpenRouter key). This is a conscious M1 tradeoff.
- **Funnel fidelity (M2):** replace the `Runtime.evaluate` collector with the full staged funnel —
  Extract (DOM+AX+geometry) → VisibilityFilter → OcclusionCuller → WrapperCollapser → SoMIndexer →
  ReadingOrderFormatter — with token-budget enforcement and dropped-count logging.
- **Adaptive per-host settle** (mean + 2·stddev, clamped).
- **Offscreen-document lifecycle** if the 20s heartbeat proves insufficient.
- **Pairing-code flow** for true multi-device/multi-user session linking.
- **Human take-over interrupt** (LangGraph `interrupt` + `Command(resume=…)`).

## 11. Files touched (M1)

**Milestone 1b (run survival):**
- `backend/app/api/run_manager.py` — **new** `RunManager` (registry, event buffer, attach/detach, GC).
- `backend/app/api/ws.py` — `/ws/run` uses `RunManager`; `start` vs `attach`; disconnect detaches not
  cancels.
- `frontend/src/lib/useAgentRun.ts` — persist `thread_id`, `attach` on load, reconcile from replay.
- Backend tests: `RunManager` unit, `/ws/run` reconnect integration.

**Milestone 1a (bridge skeleton):**
- `packages/contracts/schema/envelope.schema.json` (+ regenerate TS & Py) — add optional `id`.
- `backend/app/browser/extension_bridge.py` — **new** `ExtensionBridgeSession` + bridge hub.
- `backend/app/api/` — **new** `/ws/bridge` endpoint; wire hub + `RunManager`.
- `backend/app/config/` — `browser_backend="extension_bridge"` in settings + composition root.
- `bridge-extension/public/manifest.json` — permissions (`debugger`, `tabs`, host), toolbar action.
- `bridge-extension/src/` — WS client, funnel, dispatcher, service-worker glue (+ tests).
- Backend tests: `ExtensionBridgeSession` unit, `/ws/bridge` integration.
