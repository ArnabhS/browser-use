"""Parity for the click-doesn't-navigate fallback (see test_local_cdp_href_fallback): a trusted
click on a link that swallows its default nav must fall back to the anchor's href on the raw-CDP
backend too, or the agent loops re-clicking a dead index. Served from a local HTTP fixture because
the gate only follows real http(s) links (not data: URLs)."""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.browser.cdp_session import CDPSession
from browser_agent_contracts import ActionCall

pytestmark = pytest.mark.browser


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/recipe"):
            body = b"<h1>RECIPE PAGE</h1>"
        else:  # a real anchor whose click is swallowed by JS — trusted click never navigates
            body = (
                b'<a href="/recipe" onclick="event.preventDefault()" '
                b'style="font-size:40px;display:block;padding:40px">Keto pancakes</a>'
            )
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):  # keep the test output clean
        pass


@pytest.fixture
def base_url():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


async def test_cdp_click_on_link_that_blocks_nav_follows_href(base_url):
    s = CDPSession(headless=True, stealth=True, load_extensions=False)
    await s.start()
    try:
        await s.navigate(f"{base_url}/search")
        obs = await s.observe()
        link = next(e for e in obs.elements if "keto" in (e.name or "").lower())

        result = await s.act(ActionCall(name="click", args={"index": link.index}))

        assert "/recipe" in (await s._eval("location.href"))
        assert "RECIPE PAGE" in (await s._eval("document.body.innerText"))
        assert result.success
    finally:
        await s.stop()
