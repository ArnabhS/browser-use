from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_DEFAULT_DIR = Path(__file__).resolve().parent.parent / "prompts"


class PromptLoader:
    """Renders Jinja2 prompt templates (supports {% include %}) from app/prompts/."""

    def __init__(self, templates_dir: Path | None = None) -> None:
        self._dir = templates_dir or _DEFAULT_DIR
        self._env = Environment(
            loader=FileSystemLoader(str(self._dir)),
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=False,
            autoescape=select_autoescape(enabled_extensions=()),
        )

    def render(self, name: str, ctx: dict) -> str:
        return self._env.get_template(name).render(**ctx)

    def render_string(self, template: str, ctx: dict) -> str:
        return self._env.from_string(template).render(**ctx)


@lru_cache
def default_loader() -> PromptLoader:
    return PromptLoader()
