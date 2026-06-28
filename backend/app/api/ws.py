from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect

from app.agent.demo import run
from app.browser.local_cdp import LocalCDPSession
from app.config.container import build_default_app
from app.config.settings import get_settings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WebSocketSink:
    """EventSink that forwards every AgentEvent to a WebSocket as JSON."""

    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws

    async def emit(self, event) -> None:
        try:
            await self._ws.send_json(event.model_dump())
        except Exception:
            pass  # socket closing mid-emit — drop


async def build_running_app(sink):
    """Composition seam (tests override this): build + START a real browser app for one socket.

    Returns (graph, emitter, memory, cleanup) where cleanup() stops the browser.
    """
    settings = get_settings()
    session = LocalCDPSession(
        headless=settings.cdp_headless,
        draw_som_overlay=settings.use_vision,
        connect_url=settings.cdp_connect_url or None,
    )
    await session.start()
    graph, emitter, store, _sink, memory = build_default_app(session=session, sink=sink)

    stopped = False

    async def cleanup() -> None:
        nonlocal stopped
        if stopped:
            return
        stopped = True
        await session.stop()

    return graph, emitter, memory, cleanup


async def ws_run(websocket: WebSocket) -> None:
    await websocket.accept()
    answer_queue: asyncio.Queue[str] = asyncio.Queue()

    async def answer_provider(q: dict) -> str:
        return await answer_queue.get()

    run_task = None
    cleanup = None

    try:
        while True:
            msg = await websocket.receive_json()
            mtype = msg.get("type")

            if mtype == "answer":
                answer_queue.put_nowait(msg.get("answer", ""))

            elif mtype == "start" and (run_task is None or run_task.done()):
                task_text = msg.get("task", "")
                thread_id = msg.get("thread_id") or f"ws-{uuid.uuid4().hex[:8]}"
                try:
                    graph, emitter, memory, cleanup = await build_running_app(WebSocketSink(websocket))
                except Exception as exc:  # browser failed to start — tell the cockpit, don't crash
                    await websocket.send_json(
                        {"event": "error", "data": {"message": f"Could not start the browser: {exc}"}, "ts": _now()}
                    )
                    await websocket.send_json({"event": "run_complete", "data": {}, "ts": _now()})
                    continue

                async def _do_run(
                    graph=graph,
                    emitter=emitter,
                    memory=memory,
                    cleanup=cleanup,
                    task_text=task_text,
                    thread_id=thread_id,
                ):
                    try:
                        final = await run(
                            graph,
                            task=task_text,
                            thread_id=thread_id,
                            answer_provider=answer_provider,
                            emitter=emitter,
                            memory=memory,
                        )
                        await websocket.send_json(
                            {
                                "event": "run_complete",
                                "data": {"success": final.success, "reason": final.reason},
                                "ts": _now(),
                            }
                        )
                    except Exception as exc:
                        await websocket.send_json(
                            {"event": "error", "data": {"message": str(exc)}, "ts": _now()}
                        )
                        await websocket.send_json(
                            {"event": "run_complete", "data": {}, "ts": _now()}
                        )
                    finally:
                        if cleanup:
                            await cleanup()

                run_task = asyncio.create_task(_do_run())

            elif mtype == "stop":
                # Cancel the running agent task (stops the graph loop + LLM/browser work),
                # tear down the browser, and tell the cockpit the run ended.
                if run_task is not None and not run_task.done():
                    run_task.cancel()
                    try:
                        await run_task
                    except BaseException:
                        pass
                if cleanup:
                    try:
                        await cleanup()  # idempotent — browser may already be stopped
                    except Exception:
                        pass
                await websocket.send_json(
                    {"event": "run_complete", "data": {"stopped": True}, "ts": _now()}
                )

            # unknown messages ignored

    except WebSocketDisconnect:
        if run_task and not run_task.done():
            run_task.cancel()
        if cleanup:
            try:
                await cleanup()
            except Exception:
                pass
