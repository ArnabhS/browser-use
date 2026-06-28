from __future__ import annotations

from app.prompt.loader import PromptLoader


class PromptResolver:
    """Renders a runtime-custom template string per key, else falls back to a file."""

    def __init__(self, custom: dict[str, str] | None = None) -> None:
        self._custom = dict(custom or {})

    def render(self, key: str, ctx: dict, loader: PromptLoader, *, fallback: str) -> str:
        if key in self._custom:
            return loader.render_string(self._custom[key], ctx)
        return loader.render(fallback, ctx)
