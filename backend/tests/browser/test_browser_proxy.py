"""Routing the browser through a proxy is the only way to change the IP sites geolocate by (e.g.
an Indian proxy for Indian Amazon/Google results from a foreign-hosted server). We parse the proxy
URL into Playwright's option shape and launch with it."""
import pytest

from app.browser.local_cdp import LocalCDPSession


def test_proxy_option_parses_scheme_host_port_and_credentials():
    opt = LocalCDPSession(proxy="http://user:pass@1.2.3.4:8080")._proxy_option()
    assert opt == {"server": "http://1.2.3.4:8080", "username": "user", "password": "pass"}


def test_proxy_option_without_credentials():
    opt = LocalCDPSession(proxy="http://1.2.3.4:8080")._proxy_option()
    assert opt == {"server": "http://1.2.3.4:8080"}


def test_proxy_option_supports_socks5():
    opt = LocalCDPSession(proxy="socks5://1.2.3.4:1080")._proxy_option()
    assert opt == {"server": "socks5://1.2.3.4:1080"}


def test_proxy_option_none_when_unset():
    assert LocalCDPSession()._proxy_option() is None
    assert LocalCDPSession(proxy="   ")._proxy_option() is None


@pytest.mark.browser
async def test_launches_with_proxy_configured():
    # Unreachable proxy is fine: Chromium only uses it on navigation, and start() stays on
    # about:blank here — so this proves launch accepts our proxy option end to end.
    sess = LocalCDPSession(proxy="http://127.0.0.1:9")
    await sess.start()
    try:
        assert sess.page.url == "about:blank"
    finally:
        await sess.stop()
