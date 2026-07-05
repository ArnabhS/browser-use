# CDP foundation — replace Playwright with raw CDP (Track B)

**Date:** 2026-07-03
**Status:** Implemented (behind `browser_backend="cdp"`); one follow-up remaining — see Status below.

## Implementation status (2026-07-03, autonomous /loop, TDD, all green)

Built and verified against real Chrome (63 browser tests + 180 non-browser):
- **Launcher** `app/browser/cdp/launcher.py` — find/launch Chrome, `build_chrome_args`, ws URL.
- **`extract_cdp`** — main-frame funnel via `Runtime.evaluate` (same `EXTRACT_JS`).
- **`CDPSession`** — start/attach (fresh created target, so screencast attaches), observe, navigate,
  full action vocabulary (click, long_press, type, clear, scroll, select_option, press_key, wait_for,
  extract, **search_page/find_elements** [P0-4]), tab actions (new/switch/close/observe/open_in_new_tab)
  with new-tab adoption, stealth, **locale/timezone/geolocation emulation**, **auto-loaded extensions**
  [P0-5], and a **live-view screencast** (cdp-use event registration).
- **Wired** `browser_backend="cdp"` in `ws.py` (locale/geo + screencast); `cdp-use==1.4.5` dep added.

- **Child-frame iframe extraction** — DONE for direct children of the main frame, **both same-origin
  and cross-origin OOPIFs** (`extract_child_frames_cdp`: `getFrameTree` → `getFrameOwner`/`getBoxModel`
  for the offset → `createIsolatedWorld` + `Runtime.evaluate(contextId)`, then the Playwright offset/
  scale math). Verified live: an inner button in a srcdoc iframe extracts at the correct main-viewport
  coords and a trusted click lands inside the frame; a cross-origin data: iframe also extracts.

**Only remaining limitation:** deeper-than-one iframe nesting isn't offset-accumulated (rare; direct
children cover embedded forms). **Cutover (flip default + delete Playwright) is intentionally left to
the user** after soaking the CDP backend on real sites — see Migration.

---

**Superseded status:** Draft for review
**Related:** `2026-07-03-p0-adoptions-design.md` (Track A), `browser-use-oss-comparison` (memory),
`browser-agent-antibot` (memory).

## Goal

Replace Playwright as the browser driver with **raw Chrome DevTools Protocol**, and drop the bridge
extension from active use for now. Deliver a single server-side `BrowserSession` implementation that
launches (or attaches to) Chrome over CDP and drives it directly. Then build the two browser-dependent
P0s on it: **P0-4 `search_page`/`find_elements`** and **P0-5 auto-loaded extensions**.

## Why

- The user wants off Playwright (drop a heavy dependency; align with browser-use's proven `cdp-use`
  approach; one CDP codebase that a future bridge can share logic with).
- With the bridge paused, there is only one browser path — no two-impl cost, simpler composition.

**Consequences held consciously** (see Track A spec): the privacy split is paused (DOM extracted
server-side) and the datacenter-IP anti-bot gap returns (hard bot-walls need `BROWSER_PROXY`).

## Decisions locked

1. **CDP client: `cdp-use`.** Typed, production-proven against real Chrome; gives us target/session
   management, OOPIF auto-attach, reconnect, and per-request timeouts instead of hand-rolling them.
   Removing Playwright is a net dependency reduction.
2. **Extraction: port our funnel.** Run the existing `EXTRACT_JS` via `Runtime.evaluate` and keep the
   tested visibility → occlusion → wrapper-collapse → SoM → reading-order pipeline unchanged. Backend
   `DOMSnapshot`+AX extraction (richer, but a bigger rewrite) is explicitly a **later** enhancement,
   not part of this switch.
3. **Keep the `BrowserSession` port unchanged.** `observe()/act()/navigate()/tabs()` stay identical,
   so the graph, nodes, dispatcher, and funnel are untouched (Liskov). A reintroduced bridge later
   still satisfies the same port.
4. **Migrate behind a setting, verify, then delete Playwright.** Ship the new impl as
   `browser_backend="cdp"`, reach parity against the existing `tests/browser/*` suite, then remove
   `LocalCDPSession` + the Playwright dependency.

## Architecture — `CDPSession` over `cdp-use`

One new module `app/browser/cdp_session.py` implementing `BrowserSession`. It owns a `cdp-use` client
and maps our operations to CDP domains. Each concern is a small collaborator (SRP), mirroring the
funnel's stage-per-class discipline:

| Concern | CDP mechanism | Notes |
|---------|---------------|-------|
| **Launch** | spawn Chrome subprocess `--remote-debugging-port=0` + stealth/extension/proxy args; poll `/json/version`; connect WS | free-port bind; `--user-data-dir` temp; headful (xvfb on server) |
| **Attach** | connect to `settings.cdp_connect_url` if set | attach-to-existing-Chrome mode (no launch) |
| **Targets / tabs** | `Target.setDiscoverTargets`, `Target.setAutoAttach(flatten=True)` | track page targets; `tabs()` lists them; recursive auto-attach for OOPIFs |
| **observe** | `Runtime.evaluate(EXTRACT_JS, returnByValue)` in the focused page session → `RawElement[]`; then the **existing funnel** | per-frame eval for child iframes (`Page.getFrameTree`), offset coords — mirrors current `_extract_child_frames` |
| **screenshot** | `Page.captureScreenshot` (PNG) | feeds `use_vision` + SoM overlay |
| **click / long_press** | `Input.dispatchMouseEvent` press/(hold)/release at the SoM center coords | *simpler than Playwright* — we already resolve index→coords in the map |
| **type / press_key / clear** | focus (click), then `Input.dispatchKeyEvent` / `Input.insertText`; clear = select-all+Delete | char-by-char for trusted input |
| **scroll** | `Input.dispatchMouseEvent` mouseWheel, or `_SCROLL_AT_JS` via `Runtime.evaluate` for container scroll | keep the existing container-scroll JS |
| **select_option** | `_SELECT_JS` via `Runtime.evaluate` | unchanged JS helper |
| **navigate / new_tab / switch_tab / close_tab / open_in_new_tab / observe_tab** | `Page.navigate`, `Target.createTarget/activateTarget/closeTarget` | tab registry over targets |
| **stealth** | launch args + `Page.addScriptToEvaluateOnNewDocument` (init script, every frame) | port `_STEALTH_ARGS` / `_STEALTH_JS` verbatim |
| **locale / timezone / geolocation** | `Emulation.setLocaleOverride` / `setTimezoneOverride` / `setGeolocationOverride` | direct CDP (Playwright did these via context opts) |
| **proxy** | `--proxy-server=` arg + `Fetch.enable(handleAuthRequests)` for auth | reuse `settings.browser_proxy` |
| **screencast (live view)** | `Page.startScreencast` → `Page.screencastFrame` → `on_frame` + `screencastFrameAck` | reimplement `screencast.py` over cdp-use |
| **settle / stability** | wait on `Page.lifecycleEvent` (load / networkIdle) + adaptive per-host bound | CLAUDE.md §5 |

**Composition root:** `config/container` builds `CDPSession` when `browser_backend="cdp"`. `ws.py`
already branches on `browser_backend`; add the `cdp` branch alongside the (temporary) `local_cdp` one.

## P0-4 · `search_page` + `find_elements` (on the new session)

**What:** two read-only page-inspection tools — `search_page` greps page text for a pattern;
`find_elements` runs a CSS query returning matched tags/attrs/text. They replace "scroll blindly and
guess from a truncated list" with a deterministic "is X on the page?".

**Honest cost note:** in our one-action-per-turn loop each still costs a turn (unlike browser-use's
multi-action step) — the win is **decisiveness and fewer total steps**, plus avoiding the expensive
`Extract` LLM call for simple presence checks. (The "skip re-observe for read-only tools" routing
optimization that makes them genuinely cheap is a fast-follow, noted below.)

**Design:**
- Tool specs `SearchPage(pattern, regex=False, case_sensitive=False, max_results=25)` and
  `FindElements(selector, attributes=None, max_results=50, include_text=True)`; add to `TOOL_SPECS` +
  `BROWSER_TOOLS`.
- Dispatcher maps them to ActionCall names `search_page` / `find_elements` — they flow through the
  existing `session.act()` → `ActionResult` → `ToolMessage(content=result.reason)` path, **no new
  plumbing**; results serialized into `ActionResult.reason` (the text the model reads).
- `CDPSession`: two `Runtime.evaluate` branches (a grep JS and a `querySelectorAll` JS). **Single
  path — no extension handlers** (the bridge is out).
- Prompt: describe both in the tool list + a policy nudge to prefer them over blind scrolling / over
  `Extract` for presence & structure checks.

**Tests:** unit (fakes) — dispatcher maps both names and round-trips the serialized result; browser
(marker) — `search_page` finds seeded text and reports misses; `find_elements` returns attrs for a
selector.

## P0-5 · Auto-load reliability extensions

**What:** load **uBlock Origin Lite** (ad/tracker blocking → faster, quieter pages) and **"I still
don't care about cookies"** (auto-dismisses cookie banners → deletes a class of agent busywork) at
launch. Optionally **force-background-tab**.

**Cheap under CDP.** No Playwright persistent-context dance — just append
`--disable-extensions-except=<dirs>` + `--load-extension=<dirs>` to the Chrome launch args.

**Design:**
- Setting `load_extensions: bool = True` (off for hermetic CI).
- On first launch, download the extensions' CRX from the Chrome Web Store update endpoint and unpack
  to a cache dir (mirrors browser-use); **degrade gracefully** if offline (log + skip, never crash).
- Applies only to the launch path, not `cdp_connect_url` (the user's own Chrome keeps its extensions).

**Tests:** unit — launch args include the flags when `load_extensions` and launching (not attaching);
unit — offline download failure degrades to no-extensions without raising; browser (marker, opt-in) —
a known cookie banner is auto-dismissed.

## Migration strategy (risk control)

This is a large rewrite of a battle-tested layer, so parity is enforced, not assumed:

1. Build `CDPSession` incrementally, TDD, one concern at a time (launch → observe → each action group
   → screencast → emulation).
2. **The existing `tests/browser/*` suite is the parity harness** — the iframe extraction, `long_press`,
   stealth, hostile-element, and extract tests must pass against `CDPSession` exactly as they do
   against `LocalCDPSession`. Re-point them (or parametrize) across both impls during migration.
3. Run the real quashbugs + HubSpot-iframe flows (the cases that drove our funnel fixes) against the
   new session before switching the default.
4. Flip `browser_backend` default to `cdp`, soak, then **delete `local_cdp.py` + drop the Playwright
   dependency** in a final cleanup commit.

## Risks & mitigations

- **Regression vs the tested Playwright impl** → the browser-test parity harness above; migrate behind
  a setting so rollback is a config flip.
- **iframe / OOPIF coordinate math** (the trickiest part; our funnel offsets child-frame coords) →
  port the existing `_extract_child_frames` logic; verify against `test_extract_iframes`.
- **Reconnect / crash resilience** — start simpler than browser-use (fail the run cleanly on a dropped
  socket); add resilience only if flakiness shows.
- **cdp-use fit** — if a needed capability is missing, fall back to a thin direct `send_raw` call;
  cdp-use exposes the raw client.

## Build order

1. `CDPSession` skeleton: launch/attach + connect + targets/tabs.
2. `observe()` (funnel over `Runtime.evaluate`, incl. child frames) — gate on the extraction tests.
3. Actions, grouped: navigate/tabs → click/long_press → type/press_key/clear → scroll/select_option.
4. Screencast + stealth + locale/timezone/geo/proxy emulation.
5. Parity soak (quashbugs, iframe), flip default, delete Playwright.
6. **P0-4** `search_page`/`find_elements` (two `Runtime.evaluate` branches + tool specs).
7. **P0-5** extensions (`--load-extension` + fetch/cache helper).

## Out of scope

- Backend `DOMSnapshot`+AX extraction (later enhancement; funnel is ported as-is here).
- Reintroducing the bridge (paused; port preserved so it returns cleanly).
- The read-only-tool "skip re-observe" routing optimization (fast-follow to P0-4).
- Watchdog/event-bus architecture, cloud sync — not adopting browser-use's plumbing.

## Guardrail check

- **No raw DOM over the wire** is a *bridge* invariant; with the bridge paused and extraction
  server-side it is inapplicable now, and returns with the bridge.
- **No index reuse** preserved (funnel rebuilds fresh each turn).
- **OpenRouter key server-side** unaffected.
- **Anti-bot:** headful default retained; document that hard bot-walls now need `BROWSER_PROXY`
  (residential) since the residential-IP advantage left with the bridge.
