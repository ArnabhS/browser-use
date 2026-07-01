"""End-to-end live view: a real headless Chromium screencast must deliver at least one frame to
on_frame after the page paints, and re-point to a newly opened tab."""
import asyncio

import pytest

from app.browser.local_cdp import LocalCDPSession

pytestmark = pytest.mark.browser


async def _wait_for(pred, timeout=5.0):
    for _ in range(int(timeout / 0.1)):
        if pred():
            return
        await asyncio.sleep(0.1)


async def test_screencast_delivers_frames_for_active_page():
    frames: list[tuple[str, dict]] = []

    async def on_frame(data, meta):
        frames.append((data, meta))

    sess = LocalCDPSession()
    await sess.start()
    sess.on_frame = on_frame
    try:
        await sess.start_stream()
        await sess.page.goto("data:text/html,<body style='height:2000px'><h1>hello</h1></body>")
        # CDP screencast only emits when the compositor paints a new frame; a static page may
        # paint just once (racing startScreencast activation). Drive repaints so the assertion
        # tests the pipeline, not paint timing — in production the agent's actions/overlay do this.
        for _ in range(60):
            if frames:
                break
            try:
                await sess.page.evaluate(
                    "() => { document.body.style.background ="
                    " document.body.style.background === 'rgb(255, 0, 0)'"
                    " ? 'rgb(0, 0, 255)' : 'rgb(255, 0, 0)'; }"
                )
            except Exception:
                pass
            await asyncio.sleep(0.1)
        assert frames, "expected at least one screencast frame after the page repainted"
        assert isinstance(frames[0][0], str) and frames[0][0]  # non-empty base64
    finally:
        await sess.stop_stream()
        await sess.stop()


async def test_stream_follows_a_newly_opened_tab():
    urls: list[str] = []

    async def on_frame(data, meta):
        urls.append(meta.get("url", ""))

    sess = LocalCDPSession()
    await sess.start()
    sess.on_frame = on_frame
    try:
        await sess.start_stream()
        # Open a second tab and switch to it the way the agent does, then observe (re-points).
        page2 = await sess.page.context.new_page()
        await page2.goto("data:text/html,<body style='height:2000px'><h1>second</h1></body>")
        sess._page = page2
        await sess._ensure_stream_on_active_page()
        # Drive repaints on page2 so a frame is emitted (see note in the sibling test).
        for _ in range(60):
            if any(u.startswith("data:") for u in urls):
                break
            try:
                await page2.evaluate(
                    "() => { document.body.style.background ="
                    " document.body.style.background === 'rgb(255, 0, 0)'"
                    " ? 'rgb(0, 0, 255)' : 'rgb(255, 0, 0)'; }"
                )
            except Exception:
                pass
            await asyncio.sleep(0.1)
        assert any(u.startswith("data:") for u in urls), "stream did not follow to the new tab"
    finally:
        await sess.stop_stream()
        await sess.stop()
