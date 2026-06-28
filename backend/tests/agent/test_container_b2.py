import pytest
from app.config.container import build_default_app
from app.config.settings import Settings
from tests.fakes.fake_browser import FakeBrowserSession
from tests.fakes.fake_llm import FakeLLMClient


def test_container_uses_injected_fake_when_no_key(monkeypatch):
    from app.config import container
    monkeypatch.setattr(container, "get_settings", lambda: Settings(openrouter_api_key=""))
    graph, *_ = build_default_app(session=FakeBrowserSession(), llm=FakeLLMClient(turns=[]))
    assert graph is not None


def test_container_requires_an_llm_when_no_key(monkeypatch):
    from app.config import container
    monkeypatch.setattr(container, "get_settings", lambda: Settings(openrouter_api_key=""))
    with pytest.raises(ValueError):
        build_default_app(session=FakeBrowserSession(), llm=None)
