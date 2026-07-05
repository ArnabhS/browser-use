"""Launch (or locate) Chrome with a CDP debug port and hand back its WebSocket URL.

Replaces Playwright's launcher: we spawn the Chrome binary as a plain subprocess and talk to it over
raw CDP (cdp-use). Playwright's *bundled* Chromium binary is still a fine thing to launch — we just
no longer use the Playwright library at runtime.
"""
from __future__ import annotations

import asyncio
import glob
import logging
import os
import shutil
import socket
import tempfile

import httpx

logger = logging.getLogger(__name__)

# Stealth: strip the automation tell. The LOAD-BEARING lever is headful (see browser-agent-antibot);
# these flags are cheap defense-in-depth on top.
_STEALTH_ARGS = ["--disable-blink-features=AutomationControlled"]

# Always-on flags for automation stability (mirrors the intent of the Playwright defaults we relied
# on): no first-run UI, no throttling of backgrounded renderers, no popup blocking.
_BASE_ARGS = [
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
    "--disable-popup-blocking",
    "--disable-features=Translate",
    "--remote-allow-origins=*",
]


def find_chrome() -> str:
    """Locate a launchable Chrome/Chromium binary: explicit env → Playwright's bundle → system Chrome."""
    env = os.environ.get("CHROME_BIN") or os.environ.get("BROWSER_EXECUTABLE")
    if env and os.path.exists(env):
        return env
    pw_root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    patterns = [
        os.path.join(pw_root, "chromium-*/**/Google Chrome for Testing") if pw_root else "",
        os.path.join(pw_root, "chromium-*/chrome-linux/chrome") if pw_root else "",
        os.path.expanduser("~/Library/Caches/ms-playwright/chromium-*/**/Google Chrome for Testing"),
        os.path.expanduser("~/Library/Caches/ms-playwright/chromium-*/**/Chromium"),
        "/ms-playwright/chromium-*/chrome-linux/chrome",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for pat in patterns:
        if not pat:
            continue
        hits = sorted(glob.glob(pat, recursive=True))
        if hits:
            return hits[-1]
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError("No Chrome/Chromium binary found — set CHROME_BIN to its path.")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def build_chrome_args(
    *,
    port: int,
    user_data_dir: str,
    headless: bool,
    stealth: bool,
    proxy: str = "",
    extra: list[str] | tuple[str, ...] = (),
) -> list[str]:
    """The full Chrome command-line (pure — unit-tested)."""
    args = [f"--remote-debugging-port={port}", f"--user-data-dir={user_data_dir}", *_BASE_ARGS]
    if headless:
        args.append("--headless=new")
    if stealth:
        args += _STEALTH_ARGS
    if proxy.strip():
        args.append(f"--proxy-server={proxy.strip()}")
    args += list(extra)
    args.append("about:blank")
    return args


async def _wait_for_ws(port: int, *, timeout: float = 30.0) -> str:
    """Poll Chrome's /json/version until it reports its browser-level WebSocket URL."""
    url = f"http://127.0.0.1:{port}/json/version"
    async with httpx.AsyncClient(trust_env=False) as client:  # bypass proxy env for localhost
        for _ in range(int(timeout / 0.1)):
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.json()["webSocketDebuggerUrl"]
            except Exception:
                pass
            await asyncio.sleep(0.1)
    raise RuntimeError(f"Chrome did not expose a CDP endpoint on port {port} within {timeout}s")


async def launch_chrome(
    *,
    headless: bool = False,
    stealth: bool = True,
    proxy: str = "",
    extra_args: list[str] | tuple[str, ...] = (),
) -> tuple[asyncio.subprocess.Process, str, str]:
    """Spawn Chrome and return (process, browser_ws_url, user_data_dir). Caller owns teardown."""
    binary = find_chrome()
    port = _free_port()
    user_data_dir = tempfile.mkdtemp(prefix="cdp-agent-")
    args = build_chrome_args(port=port, user_data_dir=user_data_dir, headless=headless,
                             stealth=stealth, proxy=proxy, extra=extra_args)
    proc = await asyncio.create_subprocess_exec(
        binary, *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    try:
        ws = await _wait_for_ws(port)
    except Exception:
        proc.terminate()
        shutil.rmtree(user_data_dir, ignore_errors=True)
        raise
    return proc, ws, user_data_dir
