"""ScreencastStreamer pumps CDP screencast frames out through on_frame and acks each one.
Tested with a fake CDP session — no real browser needed (that's the integration test)."""
import asyncio

from app.browser.screencast import ScreencastStreamer


class FakeCDP:
    def __init__(self):
        self.sent: list[tuple[str, dict | None]] = []
        self._handlers: dict[str, object] = {}
        self.detached = False

    def on(self, event, handler):
        self._handlers[event] = handler

    def remove_listener(self, event, handler):
        self._handlers.pop(event, None)

    async def send(self, method, params=None):
        self.sent.append((method, params))
        return {}

    async def detach(self):
        self.detached = True

    def methods(self):
        return [m for m, _ in self.sent]

    def fire_frame(self, data, session_id):
        self._handlers["Page.screencastFrame"]({"data": data, "sessionId": session_id, "metadata": {}})


async def _wait_for(pred, timeout=1.0):
    for _ in range(int(timeout / 0.02)):
        if pred():
            return
        await asyncio.sleep(0.02)


async def test_start_issues_startscreencast_and_registers_handler():
    cdp = FakeCDP()
    s = ScreencastStreamer()
    await s.start(cdp, on_frame=_noop, url_getter=lambda: "https://x.com")
    assert "Page.startScreencast" in cdp.methods()
    assert "Page.screencastFrame" in cdp._handlers
    await s.stop()


async def test_forwards_frame_and_acks_it():
    cdp = FakeCDP()
    frames: list[tuple[str, dict]] = []

    async def on_frame(data, meta):
        frames.append((data, meta))

    s = ScreencastStreamer()
    await s.start(cdp, on_frame=on_frame, url_getter=lambda: "https://x.com")
    cdp.fire_frame("AAA", 7)

    await _wait_for(lambda: len(frames) == 1)
    assert frames[0][0] == "AAA"
    assert frames[0][1]["url"] == "https://x.com"
    await _wait_for(lambda: ("Page.screencastFrameAck", {"sessionId": 7}) in cdp.sent)
    await s.stop()


async def test_stop_stops_screencast_and_detaches():
    cdp = FakeCDP()
    s = ScreencastStreamer()
    await s.start(cdp, on_frame=_noop, url_getter=lambda: "")
    await s.stop()
    assert "Page.stopScreencast" in cdp.methods()
    assert cdp.detached
    assert "Page.screencastFrame" not in cdp._handlers


async def _noop(data, meta):
    return None
