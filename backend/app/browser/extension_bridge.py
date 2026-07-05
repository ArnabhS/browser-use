"""The backend half of the bridge (spec §6, Milestone 1a).

`ExtensionBridgeSession` is a `BrowserSession` that drives the *user's own Chrome* by relaying
`observe`/`act`/`navigate`/`tabs` over a WebSocket to the browser extension, instead of launching a
server-side Chromium. It is drop-in swappable with `LocalCDPSession` (same port), so the LangGraph
loop is unchanged.

Three small pieces, each with one job:
  • BridgeConnection — one extension socket; correlates each request to its response by `id`.
  • BridgeHub        — holds the single active connection + forwards live frames (single-user).
  • ExtensionBridgeSession — the `BrowserSession` the graph talks to; turns port calls into requests.

Only Observation / ActionCall / ActionResult cross the wire — coordinates and raw DOM stay in the
extension (CLAUDE.md §8)."""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

from browser_agent_contracts import ActionResult, Observation, Tab
from browser_agent_contracts.version import PROTOCOL_VERSION

Send = Callable[[dict], Awaitable[None]]
OnFrame = Callable[[str, dict], Awaitable[None]]


class BridgeError(RuntimeError):
    """The extension reported a failure for a request."""

    def __init__(self, message: str, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


class BridgeTimeout(BridgeError):
    """The extension did not answer a request in time."""


class BridgeDisconnected(BridgeError):
    """No extension is connected (or it dropped mid-request)."""


class BridgeConnection:
    """One extension WebSocket. `send` is an async callable that writes a JSON-able dict to it.
    Requests are matched to responses by a monotonically increasing `id`."""

    def __init__(self, send: Send, *, default_timeout: float = 15.0) -> None:
        self._send = send
        self._default_timeout = default_timeout
        self._pending: dict[str, asyncio.Future] = {}
        self._counter = 0
        self.registered = False
        self.info: dict = {}

    def _next_id(self) -> str:
        self._counter += 1
        return f"req-{self._counter}"

    async def request(self, type_: str, payload: dict, *, timeout: Optional[float] = None) -> dict:
        """Send a request envelope and await the extension's `result` payload (or raise)."""
        rid = self._next_id()
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[rid] = fut
        env = {"protocolVersion": PROTOCOL_VERSION, "type": type_, "id": rid, "payload": payload}
        try:
            await self._send(env)
        except Exception as exc:  # socket already gone
            self._pending.pop(rid, None)
            raise BridgeDisconnected(str(exc)) from exc
        try:
            return await asyncio.wait_for(fut, timeout if timeout is not None else self._default_timeout)
        except asyncio.TimeoutError:
            raise BridgeTimeout(f"no response to {type_}") from None
        finally:
            self._pending.pop(rid, None)

    def handle_incoming(self, msg: dict) -> None:
        """Route one message FROM the extension. `frame` is handled by the endpoint, not here."""
        mtype = msg.get("type")
        if mtype == "register":
            self.registered = True
            self.info = msg.get("payload", {}) or {}
            return
        if mtype not in ("result", "error"):
            return  # frame / unknown — not our concern
        rid = msg.get("id")
        fut = self._pending.get(rid) if rid else None
        if fut is None or fut.done():
            return  # stale / duplicate reply — ignore
        payload = msg.get("payload", {}) or {}
        if mtype == "result":
            fut.set_result(payload)
        else:
            fut.set_exception(BridgeError(payload.get("message", "bridge error"), payload.get("errorCode")))

    def fail_all(self, exc: Optional[Exception] = None) -> None:
        """Reject every in-flight request — the socket dropped."""
        err = exc or BridgeDisconnected("browser extension disconnected")
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(err)
        self._pending.clear()


class BridgeHub:
    """Holds the single active extension connection and forwards live frames to the active session.
    Single-user for M1: the one connected extension *is* the browser."""

    def __init__(self) -> None:
        self._conn: Optional[BridgeConnection] = None
        self.on_frame: Optional[OnFrame] = None

    @property
    def connected(self) -> bool:
        return self._conn is not None

    def set_connection(self, conn: BridgeConnection) -> None:
        self._conn = conn

    def clear_connection(self, conn: BridgeConnection) -> None:
        if self._conn is conn:
            self._conn = None

    async def request(self, type_: str, payload: dict, *, timeout: Optional[float] = None) -> dict:
        conn = self._conn
        if conn is None:
            raise BridgeDisconnected("no browser extension connected")
        return await conn.request(type_, payload, timeout=timeout)

    async def dispatch_frame(self, data_b64: str, meta: dict) -> None:
        cb = self.on_frame
        if cb is not None:
            try:
                await cb(data_b64, meta)
            except Exception:
                pass  # best-effort live view


class ExtensionBridgeSession:
    """A `BrowserSession` backed by the user's real Chrome via the bridge. Timeouts and disconnects
    become typed `ActionResult` failures (or raise on observe), never hangs — matching the graph's
    "fail with a typed ErrorCode" contract."""

    def __init__(
        self,
        hub: BridgeHub,
        *,
        observe_timeout: float = 20.0,
        act_timeout: float = 15.0,
        nav_timeout: float = 35.0,
    ) -> None:
        self._hub = hub
        self._observe_timeout = observe_timeout
        self._act_timeout = act_timeout
        self._nav_timeout = nav_timeout
        self.on_frame: Optional[OnFrame] = None

    async def start(self) -> None:
        # Nothing to launch — the browser is the user's Chrome. Route live frames to our on_frame.
        async def _forward(data_b64: str, meta: dict) -> None:
            cb = self.on_frame
            if cb is not None:
                await cb(data_b64, meta)

        self._hub.on_frame = _forward

    async def stop(self) -> None:
        if self._hub.on_frame is not None:
            self._hub.on_frame = None

    async def observe(self, *, include_som: bool = True) -> Observation:
        payload = await self._hub.request(
            "observe", {"includeSom": include_som}, timeout=self._observe_timeout
        )
        return Observation.model_validate(payload)

    async def act(self, call) -> ActionResult:
        return await self._request_result("act", call.model_dump(), self._act_timeout)

    async def navigate(self, url: str) -> ActionResult:
        return await self._request_result("navigate", {"url": url}, self._nav_timeout)

    async def tabs(self) -> list[Tab]:
        try:
            payload = await self._hub.request("tabs", {}, timeout=self._act_timeout)
        except BridgeError:
            return []
        return [Tab.model_validate(t) for t in payload.get("tabs", [])]

    async def _request_result(self, type_: str, payload: dict, timeout: float) -> ActionResult:
        try:
            result = await self._hub.request(type_, payload, timeout=timeout)
        except BridgeTimeout:
            return ActionResult(
                success=False, reason=f"the browser did not respond to {type_} in time",
                error_code="BRIDGE_TIMEOUT",
            )
        except BridgeDisconnected:
            return ActionResult(
                success=False, reason="the browser extension is not connected",
                error_code="BRIDGE_DISCONNECTED",
            )
        except BridgeError as exc:
            return ActionResult(success=False, reason=str(exc), error_code=exc.code or "ACTION_FAILED")
        return ActionResult.model_validate(result)


# One process-wide hub shared by the /ws/bridge endpoint (registers connections) and the composition
# root (builds sessions against it).
HUB = BridgeHub()
