from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect

from app.agent.demo import run
from app.api.run_manager import RunManager
from app.browser.local_cdp import LocalCDPSession
from app.config.container import build_default_app
from app.config.settings import get_settings
from app.events.protocol import AgentEvent

# Process-level registry so a run outlives the cockpit socket viewing it (spec §5). A cockpit
# refresh detaches the view; the run — and its browser — keep going and can be re-attached.
RUNS = RunManager()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def build_running_app(sink):
    """Composition seam (tests override this): build + START a real browser app for one socket.

    Returns (graph, emitter, memory, cleanup) where cleanup() stops the browser.
    """
    settings = get_settings()

    if settings.browser_backend == "extension_bridge":
        # Drive the USER'S OWN Chrome via the extension. No server-side browser to launch — but the
        # extension must already be connected (spec §6), else fail clearly rather than hang.
        from app.browser.extension_bridge import HUB, ExtensionBridgeSession

        if not HUB.connected:
            raise RuntimeError(
                "No browser connected. Open the extension and click 'Control this tab', then start again."
            )
        session = ExtensionBridgeSession(HUB)
        await session.start()
        graph, emitter, store, _sink, memory = build_default_app(session=session, sink=sink)
        session.on_frame = emitter.emit_frame  # extension frames → cockpit live view

        async def cleanup() -> None:
            await session.stop()

        return graph, emitter, memory, cleanup

    geolocation: tuple[float, float] | None = None
    if settings.browser_geolocation.strip():
        try:
            lat_s, lng_s = settings.browser_geolocation.split(",")
            geolocation = (float(lat_s), float(lng_s))
        except ValueError:
            geolocation = None  # malformed "lat,long" — skip the geo override, don't crash

    if settings.browser_backend == "cdp":
        # Raw-CDP server-side browser (Playwright-free). Screencast live-view is a follow-up increment;
        # the funnel, full action vocabulary, and locale/geo emulation are in place.
        from app.browser.cdp_session import CDPSession

        session = CDPSession(
            headless=settings.cdp_headless,
            stealth=settings.stealth,
            draw_som_overlay=settings.use_vision,
            start_url=settings.start_url,
            proxy=settings.browser_proxy,
            connect_url=settings.cdp_connect_url or None,
            locale=settings.browser_locale,
            timezone=settings.browser_timezone,
            geolocation=geolocation,
            funnel_debug=settings.funnel_debug,
            funnel_focus=settings.funnel_focus,
            load_extensions=settings.load_extensions,
        )
        await session.start()
        graph, emitter, store, _sink, memory = build_default_app(session=session, sink=sink)
        session.on_frame = emitter.emit_frame
        try:
            await session.start_stream()
        except Exception:
            pass

        async def cleanup() -> None:
            await session.stop()

        return graph, emitter, memory, cleanup

    session = LocalCDPSession(
        headless=settings.cdp_headless,
        draw_som_overlay=settings.use_vision,
        connect_url=settings.cdp_connect_url or None,
        funnel_debug=settings.funnel_debug,
        funnel_focus=settings.funnel_focus,
        start_url=settings.start_url,
        locale=settings.browser_locale,
        timezone=settings.browser_timezone,
        geolocation=geolocation,
        proxy=settings.browser_proxy,
        stealth=settings.stealth,
    )
    await session.start()
    graph, emitter, store, _sink, memory = build_default_app(session=session, sink=sink)

    # Wire the live view: the session pushes screencast frames out through the emitter, over the
    # same socket. Best-effort — if the screencast can't start, the run streams text only.
    session.on_frame = emitter.emit_frame
    try:
        await session.start_stream()
    except Exception:
        pass

    stopped = False

    async def cleanup() -> None:
        nonlocal stopped
        if stopped:
            return
        stopped = True
        try:
            await session.stop_stream()
        except Exception:
            pass
        await session.stop()

    return graph, emitter, memory, cleanup


async def _run_graph(rs, graph, emitter, memory, task_text: str, thread_id: str) -> None:
    """Drive the graph to completion, emitting lifecycle events INTO the run's fanout sink (so they
    are buffered and replay to a reconnecting cockpit). Never tears the browser down here — that is
    the job of `stop` or GC, so a refresh within the TTL can still replay the final state."""
    try:
        final = await run(
            graph,
            task=task_text,
            thread_id=thread_id,
            answer_provider=rs.answer_provider,
            emitter=emitter,
            memory=memory,
        )
        await rs.sink.emit(
            AgentEvent(event="run_complete", data={"success": final.success, "reason": final.reason})
        )
    except asyncio.CancelledError:
        raise  # stop() cancelled us; it already emitted the stopped run_complete
    except Exception as exc:
        await rs.sink.emit(AgentEvent(event="error", data={"message": str(exc)}))
        await rs.sink.emit(AgentEvent(event="run_complete", data={}))
    finally:
        RUNS.mark_done(thread_id, {})


async def ws_run(websocket: WebSocket) -> None:
    await websocket.accept()
    viewing: str | None = None  # thread_id this socket is currently attached to

    async def sender(payload: dict) -> None:
        await websocket.send_json(payload)

    async def _detach_current() -> None:
        if viewing:
            prev = RUNS.get(viewing)
            if prev is not None:
                await prev.detach(sender)

    try:
        while True:
            msg = await websocket.receive_json()
            mtype = msg.get("type")

            if mtype == "start":
                await RUNS.gc()  # opportunistic: free stale terminal runs whenever there's activity
                task_text = msg.get("task", "")
                thread_id = msg.get("thread_id") or f"ws-{uuid.uuid4().hex[:8]}"
                await _detach_current()
                rs = await RUNS.create(thread_id)
                viewing = thread_id
                await rs.attach(sender)  # empty buffer at start; goes live for this run
                try:
                    graph, emitter, memory, cleanup = await build_running_app(rs.sink)
                except Exception as exc:  # browser failed to start — tell the cockpit, don't crash
                    await rs.sink.emit(
                        AgentEvent(event="error", data={"message": f"Could not start the browser: {exc}"})
                    )
                    await rs.sink.emit(AgentEvent(event="run_complete", data={}))
                    RUNS.mark_done(thread_id, {})
                    continue
                task = asyncio.create_task(
                    _run_graph(rs, graph, emitter, memory, task_text, thread_id)
                )
                rs.bind(task, cleanup)

            elif mtype == "attach":
                # Reconnect: re-attach this socket to a still-live run and replay its history.
                thread_id = msg.get("thread_id", "")
                rs = RUNS.get(thread_id)
                if rs is None:
                    # Run is gone (finished + GC'd, or never existed) — tell the cockpit to reset.
                    await sender({"event": "run_absent", "data": {"threadId": thread_id}, "ts": _now()})
                    continue
                await _detach_current()
                viewing = thread_id
                await rs.attach(sender)  # replays buffered events (incl. run_complete if finished)

            elif mtype == "answer":
                rs = RUNS.get(viewing) if viewing else None
                if rs is not None:
                    await rs.answer(msg.get("answer", ""))

            elif mtype == "stop":
                if viewing is not None:
                    rs = RUNS.get(viewing)
                    if rs is not None:
                        await rs.sink.emit(AgentEvent(event="run_complete", data={"stopped": True}))
                    await RUNS.remove(viewing)

            # unknown messages ignored

    except WebSocketDisconnect:
        # The cockpit went away (refresh/close). Detach the view only — the run keeps running and
        # can be re-attached later with the same thread_id. This is the whole point of §5.
        await _detach_current()
