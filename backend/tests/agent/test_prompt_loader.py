from pathlib import Path
from app.prompt.loader import PromptLoader
from app.prompt.resolver import PromptResolver


def test_loader_renders_template_with_includes(tmp_path: Path):
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "part.jinja2").write_text("PART:{{ x }}")
    (tmp_path / "agent" / "main.jinja2").write_text("MAIN {% include 'agent/part.jinja2' %}")
    out = PromptLoader(templates_dir=tmp_path).render("agent/main.jinja2", {"x": "Y"})
    assert out == "MAIN PART:Y"


def test_resolver_prefers_custom_then_falls_back(tmp_path: Path):
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "sys.jinja2").write_text("FILE {{ x }}")
    loader = PromptLoader(templates_dir=tmp_path)
    r = PromptResolver({"agent_system": "CUSTOM {{ x }}"})
    assert r.render("agent_system", {"x": "1"}, loader, fallback="agent/sys.jinja2") == "CUSTOM 1"
    r2 = PromptResolver(None)
    assert r2.render("agent_system", {"x": "1"}, loader, fallback="agent/sys.jinja2") == "FILE 1"
