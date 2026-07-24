"""BrowserSession over RAW CDP (cdp-use) — the Playwright-free browser driver.

Implements the same `BrowserSession` port as `LocalCDPSession` (observe/act/navigate/tabs), so the
graph, nodes, dispatcher, and funnel are untouched. Built incrementally with a browser-test parity
harness; ships behind `browser_backend="cdp"` while Playwright stays the default until it's soaked.

Covered: launch/attach, observe (main-frame funnel), navigate, the full action vocabulary
(click, long_press, type, clear, scroll, select_option, press_key, wait_for, extract,
search_page, find_elements) and the tab actions (new/switch/close/observe/open_in_new_tab) with
new-tab adoption after clicks; plus stealth, locale/timezone/geolocation emulation, auto-loaded
reliability extensions, a live-view screencast, the Set-of-Marks overlay on the vision screenshot
(draw_som_overlay), and child-frame (iframe) extraction for direct children of the main frame — both
same-origin and cross-origin OOPIFs (see extract_cdp).

Only remaining limitation vs LocalCDPSession: deeper-than-one iframe nesting is not offset-accumulated
(direct children cover embedded forms like HubSpot/Typeform/Stripe).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import shutil

from browser_agent_contracts import ActionCall, ActionResult, Observation, Tab

from app.browser.cdp.launcher import launch_chrome
from app.browser.select_support import SELECT_JS, select_result
from app.observation.extract_cdp import eval_json, extract_cdp
from app.observation.funnel.pipeline import run_funnel
from app.observation.page_query import (
    FIND_JS,
    SEARCH_JS,
    find_args,
    format_find,
    format_search,
    search_args,
)

logger = logging.getLogger(__name__)

# Runs before page scripts in every frame — hides the automation tells (mirrors LocalCDPSession).
_STEALTH_JS = (
    "(() => {"
    "  try { Object.defineProperty(navigator, 'webdriver', { get: () => undefined }); } catch (e) {}"
    "  try { if (!window.chrome) { window.chrome = { runtime: {} }; } } catch (e) {}"
    "  try { if (!navigator.languages || !navigator.languages.length) {"
    "    Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en'] }); } } catch (e) {}"
    "})();"
)


# The href of the anchor at a viewport point (for open_in_new_tab + the click-nav fallback).
_HREF_JS = r"""
([cx, cy]) => {
  let el = document.elementFromPoint(cx, cy);
  const a = el && (el.tagName === 'A' ? el : el.closest('a'));
  return a && a.href ? a.href : null;
}
"""


def _navigable_href(href: str | None, current_url: str) -> str | None:
    """A hyperlink worth following as a click fallback: an http(s) target that is a different page
    than where we are (ignoring the #fragment). Mirrors LocalCDPSession — kept local so the CDP
    backend has no Playwright import. Rejects javascript:/mailto:/tel:, empty, and in-page anchors."""
    if not href:
        return None
    low = href.lower()
    if not (low.startswith("http://") or low.startswith("https://")):
        return None
    if href.split("#", 1)[0] == current_url.split("#", 1)[0]:
        return None
    return href

# Set-of-Marks overlay: draw a numbered, colored box on each interactable so the vision screenshot
# the model reads matches the [N] index list. Coords are viewport-space (funnel index_boxes), so the
# overlay uses fixed positioning — iframe elements (already offset into the main viewport) line up too.
_SOM_OVERLAY_JS = r"""
(boxes) => {
  const old = document.getElementById('__som_overlay__'); if (old) old.remove();
  const c = document.createElement('div');
  c.id = '__som_overlay__';
  c.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;pointer-events:none;z-index:2147483647';
  const colors = ['#E6194B','#3CB44B','#4363D8','#F58231','#911EB4','#008080','#F032E6','#BFEF45'];
  for (const b of boxes) {
    const idx=b[0], x=b[1], y=b[2], w=b[3], h=b[4], col=colors[idx % colors.length];
    const box = document.createElement('div');
    box.style.cssText = `position:absolute;left:${x}px;top:${y}px;width:${w}px;height:${h}px;border:2px solid ${col};box-sizing:border-box`;
    const lab = document.createElement('div');
    lab.textContent = idx;
    lab.style.cssText = `position:absolute;left:${x}px;top:${Math.max(0,y-14)}px;background:${col};color:#fff;font:bold 11px monospace;padding:0 3px;line-height:14px`;
    c.appendChild(box); c.appendChild(lab);
  }
  document.body.appendChild(c);
}
"""
_SOM_REMOVE_JS = "(() => { const o = document.getElementById('__som_overlay__'); if (o) o.remove(); })()"

# Common non-text keys the agent presses. windowsVirtualKeyCode is what most sites read.
_KEYS = {
    "enter": ("Enter", "Enter", 13), "return": ("Enter", "Enter", 13),
    "tab": ("Tab", "Tab", 9), "escape": ("Escape", "Escape", 27), "esc": ("Escape", "Escape", 27),
    "backspace": ("Backspace", "Backspace", 8), "delete": ("Delete", "Delete", 46),
    "arrowdown": ("ArrowDown", "ArrowDown", 40), "arrowup": ("ArrowUp", "ArrowUp", 38),
}

_ACTION_TIMEOUT = {"navigate": 30.0, "click": 10.0, "long_press": 15.0, "type": 10.0, "scroll": 5.0,
                   "wait_for": 30.0, "extract": 15.0, "press_key": 5.0, "clear": 10.0,
                   "select_option": 10.0, "new_tab": 30.0, "switch_tab": 5.0, "close_tab": 5.0,
                   "observe_tab": 5.0, "open_in_new_tab": 30.0}


class _TargetTabs:
    """Stable integer tab ids for CDP page targets (keyed by targetId) — monotonic, no reuse on close.
    Ids are assigned at CREATION time via register() (getTargets order is not creation order), so the
    agent's "tab 1" is the first tab it opened. Mirrors TabRegistry's semantics for string targetIds."""

    def __init__(self) -> None:
        self._ids: dict[str, int] = {}
        self._next = 0

    def register(self, target_id: str) -> int:
        if target_id not in self._ids:
            self._ids[target_id] = self._next
            self._next += 1
        return self._ids[target_id]

    def sync(self, target_ids: list[str]) -> None:
        for tid in target_ids:
            self.register(tid)
        live = set(target_ids)
        for tid in list(self._ids):
            if tid not in live:
                del self._ids[tid]

    def id_of(self, target_id: str) -> int | None:
        return self._ids.get(target_id)

    def target_for(self, tab_id: int, target_ids: list[str]) -> str | None:
        for tid in target_ids:
            if self._ids.get(tid) == tab_id:
                return tid
        return None


class CDPSession:
    def __init__(
        self,
        *,
        headless: bool = False,
        stealth: bool = True,
        start_url: str = "",
        proxy: str = "",
        connect_url: str | None = None,
        locale: str = "",
        timezone: str = "",
        geolocation: tuple[float, float] | None = None,
        draw_som_overlay: bool = False,
        funnel_debug: bool = False,
        funnel_focus: str = "",
        extra_args: list[str] | tuple[str, ...] = (),
        load_extensions: bool = True,
        extensions_dir: str = "",
        **_ignored,
    ) -> None:
        self._headless = headless
        self._stealth = stealth
        self._start_url = start_url
        self._proxy = proxy
        self._connect_url = connect_url
        self._locale = locale
        self._timezone = timezone
        self._geolocation = geolocation
        self._draw_overlay = draw_som_overlay
        self._funnel_debug = funnel_debug
        self._funnel_focus = funnel_focus
        self._extra_args = list(extra_args)
        self._load_extensions = load_extensions
        self._extensions_dir = extensions_dir or os.path.expanduser("~/.cache/browser-agent/extensions")
        self._client = None
        self._proc = None
        self._user_data_dir: str | None = None
        self._sid: str | None = None          # active page's CDP session
        self._target_id: str | None = None
        self._sessions: dict[str, str] = {}   # targetId -> sessionId (attach once, reuse)
        self._tabs = _TargetTabs()
        self._known_targets: set[str] = set()
        self.index_map: dict[int, tuple[float, float]] = {}
        self.index_boxes: dict[int, tuple[float, float, float, float]] = {}
        self.latest_screenshot: bytes | None = None
        self._shot_counter = 0
        self._last_url = ""
        # Live view: a best-effort CDP screencast of the active page pushed out through on_frame.
        self.on_frame = None
        self._streaming = False
        self._frame_queue: asyncio.Queue | None = None
        self._stream_task: asyncio.Task | None = None
        self._stream_sid: str | None = None
        self._screencast_registered = False

    # ---- lifecycle ----------------------------------------------------------
    async def start(self) -> None:
        from cdp_use import CDPClient

        if self._connect_url:
            ws = self._connect_url.replace("://localhost", "://127.0.0.1")
        else:
            extra = list(self._extra_args)
            if self._locale:
                extra.append(f"--lang={self._locale}")  # native navigator.language (Intl via Emulation)
            if self._load_extensions:
                from app.browser.cdp.extensions import ensure_extensions, extension_args
                extra += extension_args(await ensure_extensions(self._extensions_dir))
            self._proc, ws, self._user_data_dir = await launch_chrome(
                headless=self._headless, stealth=self._stealth, proxy=self._proxy,
                extra_args=extra,
            )
        self._client = CDPClient(ws)
        await self._client.start()
        await self._client.send.Target.setDiscoverTargets(params={"discover": True})
        # Create a FRESH target and use it — the pre-existing launch tab isn't a compositor-active
        # page (Page.startScreencast rejects it: "Not attached to an active page"); a created one is.
        stale = await self._page_target_ids()
        created = await self._client.send.Target.createTarget(params={"url": "about:blank"})
        await self._switch_to(created["targetId"])
        self._tabs.register(created["targetId"])  # our tab is id 0
        if not self._connect_url:  # never close the user's own tabs in connect mode
            for tid in stale:
                try:
                    await self._client.send.Target.closeTarget(params={"targetId": tid})
                except Exception:
                    pass
        if self._geolocation:
            try:  # let getCurrentPosition return the override without a prompt
                await self._client.send.Browser.grantPermissions(params={"permissions": ["geolocation"]})
            except Exception:
                pass
        self._known_targets = set(await self._page_target_ids())
        if self._start_url:
            try:
                await self.navigate(self._start_url)
            except Exception as exc:
                logger.warning("start_url navigation to %s failed: %s", self._start_url, exc)

    async def stop(self) -> None:
        try:
            await self.stop_stream()
        except Exception:
            pass
        if self._client is not None:
            try:
                await self._client.stop()
            except Exception:
                pass
        if self._proc is not None:
            try:
                self._proc.terminate()
                await self._proc.wait()
            except Exception:
                pass
        if self._user_data_dir:
            shutil.rmtree(self._user_data_dir, ignore_errors=True)

    # ---- targets / sessions -------------------------------------------------
    async def _page_target_ids(self) -> list[str]:
        targets = await self._client.send.Target.getTargets()
        return [t["targetId"] for t in targets["targetInfos"] if t["type"] == "page"]

    async def _attach_target(self, target_id: str) -> str:
        sid = self._sessions.get(target_id)
        if sid:
            return sid
        attached = await self._client.send.Target.attachToTarget(
            params={"targetId": target_id, "flatten": True}
        )
        sid = attached["sessionId"]
        self._sessions[target_id] = sid
        for domain in ("Page", "Runtime", "DOM"):
            try:
                await getattr(self._client.send, domain).enable(session_id=sid)
            except Exception:
                pass
        if self._stealth:
            try:
                await self._client.send.Page.addScriptToEvaluateOnNewDocument(
                    params={"source": _STEALTH_JS}, session_id=sid
                )
            except Exception:
                pass
        if self._locale:
            langs = json.dumps([self._locale, self._locale.split("-")[0]])
            loc_js = (
                "(() => { try {"
                f" Object.defineProperty(navigator, 'language', {{ get: () => {json.dumps(self._locale)} }});"
                f" Object.defineProperty(navigator, 'languages', {{ get: () => {langs} }});"
                " } catch (e) {} })();"
            )
            try:
                await self._client.send.Page.addScriptToEvaluateOnNewDocument(
                    params={"source": loc_js}, session_id=sid
                )
            except Exception:
                pass
        await self._apply_emulation(sid)
        return sid

    async def _apply_emulation(self, sid: str) -> None:
        """Locale / timezone / geolocation overrides so pages see a consistent region (India by
        default) — shapes navigator.language, the Intl timezone, and the JS Geolocation API. Does NOT
        change the outbound IP (that needs a proxy). Best-effort per override."""
        async def _emul(method: str, params: dict) -> None:
            try:
                await getattr(self._client.send.Emulation, method)(params=params, session_id=sid)
            except Exception:
                pass

        if self._locale:
            await _emul("setLocaleOverride", {"locale": self._locale})
        if self._timezone:
            await _emul("setTimezoneOverride", {"timezoneId": self._timezone})
        if self._geolocation:
            lat, lng = self._geolocation
            await _emul("setGeolocationOverride", {"latitude": lat, "longitude": lng, "accuracy": 100})

    async def _switch_to(self, target_id: str) -> None:
        self._target_id = target_id
        self._sid = await self._attach_target(target_id)
        try:
            await self._client.send.Target.activateTarget(params={"targetId": target_id})
        except Exception:
            pass

    async def _follow_unseen_tab(self) -> None:
        """If a tab opened since we last looked, follow the newest before observing."""
        ids = await self._page_target_ids()
        unseen = [tid for tid in ids if tid not in self._known_targets]
        self._known_targets = set(ids)
        if unseen and unseen[-1] != self._target_id:
            await self._switch_to(unseen[-1])

    # ---- CDP helpers --------------------------------------------------------
    async def _send(self, domain: str, method: str, params: dict | None = None):
        dom = getattr(self._client.send, domain)
        fn = getattr(dom, method)
        if params is None:
            return await fn(session_id=self._sid)
        return await fn(params=params, session_id=self._sid)

    async def _eval(self, expression: str):
        return await eval_json(self._client, self._sid, expression)

    # ---- observe ------------------------------------------------------------
    async def observe(self, *, include_som: bool = True) -> Observation:
        await self._follow_unseen_tab()
        await self._ensure_stream_on_active()
        raw, meta = await extract_cdp(self._client, self._sid)
        self._last_url = meta.url
        self._shot_counter += 1
        ref = f"shot-{self._shot_counter}"
        focus = self._funnel_focus if self._funnel_debug else None
        observation, self.index_map, self.index_boxes = run_funnel(
            raw, meta, screenshot_ref=ref, debug_focus=focus
        )
        observation.tabs = await self._tab_snapshot()
        # Draw the SoM overlay INTO the vision screenshot so the model can match the [N] list to the
        # image, then remove it so it never interferes with a subsequent action's hit-testing.
        if self._draw_overlay and self.index_boxes:
            try:
                boxes = [[i, *b] for i, b in self.index_boxes.items()]
                await self._eval(f"({_SOM_OVERLAY_JS})({json.dumps(boxes)})")
                self.latest_screenshot = await self._screenshot()
                await self._eval(_SOM_REMOVE_JS)
            except Exception:
                self.latest_screenshot = await self._screenshot()
        else:
            self.latest_screenshot = await self._screenshot()
        return observation

    async def _screenshot(self) -> bytes | None:
        try:
            shot = await self._send("Page", "captureScreenshot", {"format": "png"})
            return base64.b64decode(shot["data"])
        except Exception:
            return None

    # ---- navigate / settle --------------------------------------------------
    async def navigate(self, url: str) -> ActionResult:
        await self._send("Page", "navigate", {"url": url})
        await self._settle()
        return ActionResult(success=True, reason=f"navigated to {url}")

    async def _settle(self, bound: float = 5.0) -> None:
        for _ in range(int(bound / 0.1)):
            try:
                if await self._eval("document.readyState") == "complete":
                    break
            except Exception:
                pass
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.3)  # brief DOM/network quiet before observing

    async def _viewport(self) -> tuple[int, int]:
        try:
            vw = int(await self._eval("window.innerWidth")) or 1280
            vh = int(await self._eval("window.innerHeight")) or 720
            return vw, vh
        except Exception:
            return 1280, 720

    # ---- actions ------------------------------------------------------------
    async def act(self, call: ActionCall) -> ActionResult:
        timeout = _ACTION_TIMEOUT.get(call.name, 10.0)
        try:
            return await asyncio.wait_for(self._dispatch(call), timeout=timeout)
        except asyncio.TimeoutError:
            return ActionResult(success=False, reason=f"{call.name} timed out after {timeout}s",
                                errorCode="ACTION_TIMEOUT")
        except Exception as e:
            return ActionResult(success=False, reason=f"{call.name} failed: {e}", errorCode="ACTION_ERROR")

    async def _dispatch(self, call: ActionCall) -> ActionResult:
        name, args = call.name, call.args
        if name == "navigate":
            return await self.navigate(args["url"])
        if name == "click":
            return await self._click(args)
        if name == "long_press":
            return await self._long_press(args)
        if name == "type":
            return await self._type(args)
        if name == "clear":
            return await self._clear(args)
        if name == "scroll":
            return await self._scroll(args)
        if name == "select_option":
            return await self._select_option(args)
        if name == "press_key":
            return await self._press_key(str(args["key"]))
        if name == "wait_for":
            await asyncio.sleep(min(float(args.get("seconds", 1.0)), 10.0))
            return ActionResult(success=True, reason="waited")
        if name == "extract":
            text = (await self._eval("document.body.innerText") or "")[:4000]
            return ActionResult(success=True, reason=text)
        if name == "search_page":
            res = await self._eval(f"({SEARCH_JS})({json.dumps(search_args(args))})")
            return ActionResult(success=not (res or {}).get("error"), reason=format_search(res))
        if name == "find_elements":
            res = await self._eval(f"({FIND_JS})({json.dumps(find_args(args))})")
            return ActionResult(success=not (res or {}).get("error"), reason=format_find(res))
        if name in {"new_tab", "switch_tab", "close_tab", "observe_tab", "open_in_new_tab"}:
            return await self._tab_action(name, args)
        return ActionResult(success=False, reason=f"action '{name}' not yet supported on the CDP backend")

    def _coords(self, args) -> tuple[float, float] | None:
        return self.index_map.get(int(args["index"]))

    async def _mouse(self, kind: str, x: float, y: float, *, click_count: int = 1) -> None:
        params = {"type": kind, "x": x, "y": y}
        if kind in ("mousePressed", "mouseReleased"):
            params.update({"button": "left", "clickCount": click_count})
        await self._send("Input", "dispatchMouseEvent", params)

    async def _mouse_click(self, x: float, y: float, *, click_count: int = 1) -> None:
        await self._mouse("mouseMoved", x, y)
        await self._mouse("mousePressed", x, y, click_count=click_count)
        await self._mouse("mouseReleased", x, y, click_count=click_count)

    async def _click(self, args) -> ActionResult:
        geo = self._coords(args)
        if geo is None:
            return ActionResult(success=False, reason=f"stale index {args.get('index')}")
        before = set(await self._page_target_ids())
        url_before = await self._eval("location.href")
        await self._mouse_click(*geo)
        await self._settle()
        followed = await self._adopt_new_tab(before)
        tab = " (followed new tab)" if followed else ""
        # Click-doesn't-navigate fallback (see _navigable_href): some links swallow a trusted click
        # and never move the page, so the agent re-clicks the same dead index. If the click landed
        # on a real hyperlink and nothing changed, follow its href directly.
        if not followed and (await self._eval("location.href")) == url_before:
            href = _navigable_href(await self._eval(f"({_HREF_JS})({json.dumps(list(geo))})"), url_before)
            if href:
                try:
                    await self.navigate(href)
                    tab = " (via link href)"
                except Exception:  # bad/blocked href — leave as-is, agent will retry
                    pass
        return ActionResult(success=True, reason=f"click at [{args['index']}]{tab}")

    async def _long_press(self, args) -> ActionResult:
        geo = self._coords(args)
        if geo is None:
            return ActionResult(success=False, reason=f"stale index {args.get('index')}")
        cx, cy = geo
        duration = min(max(int(args.get("duration_ms", 800)), 0), 5000) / 1000
        before = set(await self._page_target_ids())
        await self._mouse("mouseMoved", cx, cy)
        await self._mouse("mousePressed", cx, cy)
        await asyncio.sleep(duration)
        await self._mouse("mouseReleased", cx, cy)
        await self._settle()
        tab = " (followed new tab)" if await self._adopt_new_tab(before) else ""
        return ActionResult(success=True, reason=f"long-pressed [{args['index']}] for {int(duration * 1000)}ms{tab}")

    async def _type(self, args) -> ActionResult:
        geo = self._coords(args)
        if geo is None:
            return ActionResult(success=False, reason=f"stale index {args.get('index')}")
        await self._mouse_click(*geo)
        await self._send("Input", "insertText", {"text": str(args.get("text", ""))})
        await self._settle()
        return ActionResult(success=True, reason=f"typed into [{args['index']}]")

    async def _clear(self, args) -> ActionResult:
        geo = self._coords(args)
        if geo is None:
            return ActionResult(success=False, reason=f"stale index {args.get('index')}")
        await self._mouse_click(*geo, click_count=3)  # select all
        await self._press_key("Delete")
        return ActionResult(success=True, reason=f"cleared [{args['index']}]")

    async def _select_option(self, args) -> ActionResult:
        geo = self._coords(args)
        if geo is None:
            return ActionResult(success=False, reason=f"stale index {args.get('index')}")
        cx, cy = geo
        res = await self._eval(f"({SELECT_JS})({json.dumps([cx, cy, str(args['value'])])})")
        await self._settle()
        return select_result(res, args["value"])

    async def _press_key(self, key: str) -> ActionResult:
        spec = _KEYS.get(key.lower())
        if spec is None and len(key) == 1:
            spec = (key, f"Key{key.upper()}", ord(key.upper()))
        if spec is None:
            return ActionResult(success=False, reason=f"unsupported key {key!r}")
        k, code, vk = spec
        for kind in ("keyDown", "keyUp"):
            await self._send("Input", "dispatchKeyEvent",
                             {"type": kind, "key": k, "code": code, "windowsVirtualKeyCode": vk})
        await self._settle()
        return ActionResult(success=True, reason=f"pressed {key}")

    async def _scroll(self, args) -> ActionResult:
        direction = args.get("direction", "down")
        steps = int(args.get("amount", 1))
        vw, vh = await self._viewport()
        dy = int(vh * steps) * (-1 if direction == "up" else 1)
        y0 = await self._eval("window.scrollY")
        await self._send("Input", "dispatchMouseEvent",
                         {"type": "mouseWheel", "x": vw / 2, "y": vh / 2, "deltaX": 0, "deltaY": dy})
        await self._settle()
        moved = abs((await self._eval("window.scrollY")) - (y0 or 0)) > 1
        if moved:
            return ActionResult(success=True, reason=f"scrolled {direction}")
        return ActionResult(success=False, reason=f"could not scroll {direction} — already at the page edge")

    # ---- live view (screencast) ---------------------------------------------
    async def start_stream(self) -> None:
        """Begin a best-effort CDP screencast of the active page, pushed out through on_frame."""
        if self.on_frame is None or self._streaming:
            return
        self._streaming = True
        self._frame_queue = asyncio.Queue(maxsize=4)
        if not self._screencast_registered:
            self._client.register.Page.screencastFrame(self._on_screencast_frame)
            self._screencast_registered = True
        self._stream_task = asyncio.create_task(self._pump_frames())
        await self._start_screencast_on_active()

    async def stop_stream(self) -> None:
        self._streaming = False
        if self._stream_task is not None:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except BaseException:
                pass
            self._stream_task = None
        try:
            await self._send("Page", "stopScreencast")
        except Exception:
            pass

    async def _start_screencast_on_active(self) -> None:
        self._stream_sid = self._sid
        try:
            await self._send("Page", "startScreencast",
                             {"format": "jpeg", "quality": 50, "maxWidth": 960,
                              "maxHeight": 640, "everyNthFrame": 1})
        except Exception as exc:
            logger.warning("cdp screencast start failed (live view disabled): %s", exc)

    async def _ensure_stream_on_active(self) -> None:
        """Follow tab switches: re-point the screencast to the newly-active page's session."""
        if self._streaming and self._stream_sid != self._sid:
            await self._start_screencast_on_active()

    def _on_screencast_frame(self, event, session_id=None) -> None:
        # Sync CDP callback: hand the frame to the async pump; drop if it's behind (newer frame wins).
        if self._frame_queue is None:
            return
        try:
            self._frame_queue.put_nowait((event.get("data", ""), event.get("sessionId")))
        except asyncio.QueueFull:
            pass

    async def _pump_frames(self) -> None:
        assert self._frame_queue is not None
        while True:
            data, frame_sid = await self._frame_queue.get()
            if self.on_frame is not None and data:
                try:
                    await self.on_frame(data, {"url": self._last_url})
                except Exception:
                    pass
            try:  # ack the frame's own session so Chrome keeps them coming
                await self._client.send.Page.screencastFrameAck(
                    params={"sessionId": frame_sid}, session_id=self._sid
                )
            except Exception:
                pass

    # ---- tabs ---------------------------------------------------------------
    async def _adopt_new_tab(self, before: set) -> bool:
        """If the last action opened a new tab, make it active so the next observe reflects it."""
        for _ in range(30):
            ids = await self._page_target_ids()
            new = [tid for tid in ids if tid not in before]
            if new:
                self._tabs.register(new[-1])  # id in creation order, before any getTargets sync
                await self._switch_to(new[-1])
                self._known_targets = set(ids)
                await self._settle()
                return True
            await asyncio.sleep(0.1)
        return False

    async def _resolve_tab(self, stable_id) -> str | None:
        ids = await self._page_target_ids()
        self._tabs.sync(ids)
        try:
            target_num = int(stable_id)
        except (TypeError, ValueError):
            return None
        return self._tabs.target_for(target_num, ids)

    async def _tab_action(self, name: str, args) -> ActionResult:
        if name == "new_tab":
            created = await self._client.send.Target.createTarget(params={"url": args["url"]})
            self._tabs.register(created["targetId"])
            await self._switch_to(created["targetId"])
            self._known_targets = set(await self._page_target_ids())
            await self._settle()
            return ActionResult(success=True, reason=f"opened {args['url']}")
        if name == "open_in_new_tab":
            geo = self._coords(args)
            if geo is None:
                return ActionResult(success=False, reason=f"stale index {args.get('index')}")
            href = await self._eval(f"({_HREF_JS})({json.dumps(list(geo))})")
            if not href:
                return ActionResult(success=False, reason="no link at that element to open in a new tab")
            created = await self._client.send.Target.createTarget(params={"url": href})
            new_id = self._tabs.register(created["targetId"])
            # Background it — stay on the current tab; mark seen so observe won't auto-follow.
            self._known_targets = set(await self._page_target_ids())
            return ActionResult(success=True,
                                reason=f"opened link in new tab {new_id} (still on current tab)")
        # switch / close / observe resolve a stable id to a live target
        tid = await self._resolve_tab(args["target_id"])
        if tid is None:
            return ActionResult(success=False, reason=f"no tab {args['target_id']}")
        if name == "observe_tab":
            targets = await self._client.send.Target.getTargets()
            info = next((t for t in targets["targetInfos"] if t["targetId"] == tid), {})
            return ActionResult(success=True,
                                reason=f'tab {args["target_id"]}: "{info.get("title", "")}" — {info.get("url", "")}')
        if name == "switch_tab":
            await self._switch_to(tid)
            self._known_targets = set(await self._page_target_ids())
            return ActionResult(success=True, reason=f"switched to tab {args['target_id']}")
        # close_tab
        await self._client.send.Target.closeTarget(params={"targetId": tid})
        self._sessions.pop(tid, None)
        if tid == self._target_id:
            remaining = await self._page_target_ids()
            if remaining:
                await self._switch_to(remaining[-1])
            else:
                self._target_id, self._sid = None, None
        self._known_targets = set(await self._page_target_ids())
        return ActionResult(success=True, reason=f"closed tab {args['target_id']}")

    async def tabs(self) -> list[Tab]:
        return await self._tab_snapshot()

    async def _tab_snapshot(self) -> list[Tab]:
        try:
            targets = await self._client.send.Target.getTargets()
        except Exception:
            return []
        page_targets = [t for t in targets["targetInfos"] if t["type"] == "page"]
        self._tabs.sync([t["targetId"] for t in page_targets])
        out: list[Tab] = []
        for t in page_targets:
            tid = self._tabs.id_of(t["targetId"])
            if tid is None:
                continue
            out.append(Tab(id=tid, title=t.get("title", ""), url=t.get("url", ""),
                           active=(t["targetId"] == self._target_id)))
        return sorted(out, key=lambda x: int(x.id))
