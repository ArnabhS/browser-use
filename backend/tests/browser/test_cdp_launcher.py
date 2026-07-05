"""Track B: launch Chrome as a subprocess with a CDP debug port (replacing Playwright's launcher).
The arg builder is pure and unit-tested; the actual launch is a browser-marked integration test."""
import pytest

from app.browser.cdp.launcher import build_chrome_args


def test_build_args_includes_port_userdatadir_and_stealth():
    args = build_chrome_args(port=9999, user_data_dir="/tmp/x", headless=True, stealth=True)
    assert "--remote-debugging-port=9999" in args
    assert "--user-data-dir=/tmp/x" in args
    assert "--headless=new" in args
    assert "--disable-blink-features=AutomationControlled" in args


def test_build_args_headful_and_no_stealth_omit_those_flags():
    args = build_chrome_args(port=1, user_data_dir="/tmp/x", headless=False, stealth=False)
    assert not any("headless" in a for a in args)
    assert not any("AutomationControlled" in a for a in args)


def test_build_args_carries_proxy_and_extra():
    args = build_chrome_args(port=1, user_data_dir="/tmp/x", headless=False, stealth=False,
                             proxy="http://p:8080", extra=["--load-extension=/e"])
    assert "--proxy-server=http://p:8080" in args
    assert "--load-extension=/e" in args


@pytest.mark.browser
async def test_launch_chrome_exposes_a_cdp_websocket():
    import shutil

    from app.browser.cdp.launcher import launch_chrome

    proc, ws, udd = await launch_chrome(headless=True)
    try:
        assert ws.startswith("ws://")
    finally:
        proc.terminate()
        await proc.wait()
        shutil.rmtree(udd, ignore_errors=True)
