"""The observation must surface a stable tab table so the agent reasons about tabs
explicitly (instead of us silently swapping the active page under it)."""
from browser_agent_contracts import Observation, Tab, Viewport

from app.agent.format import format_observation


def _obs(tabs):
    return Observation(
        url="https://a.com", title="A",
        viewport=Viewport(width=800, height=600), elements=[], tabs=tabs,
    )


def test_observation_tabs_defaults_to_empty():
    obs = Observation(url="https://a.com", viewport=Viewport(width=1, height=1))
    assert obs.tabs == []


def test_open_tabs_block_listed_when_multiple():
    obs = _obs([
        Tab(id=0, title="YouTube", url="https://youtube.com", active=True),
        Tab(id=1, title="Product", url="https://shop.com/p", active=False),
    ])
    out = format_observation(obs)
    assert "Open tabs:" in out
    assert "[0]" in out and "YouTube" in out and "(active)" in out
    assert "[1]" in out and "Product" in out


def test_no_open_tabs_block_for_single_tab():
    obs = _obs([Tab(id=0, title="A", url="https://a.com", active=True)])
    assert "Open tabs:" not in format_observation(obs)
