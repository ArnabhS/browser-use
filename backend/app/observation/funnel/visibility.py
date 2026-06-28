from __future__ import annotations

from app.observation.raw import RawElement


class VisibilityFilter:
    """Drop elements that are not visible or have zero area."""

    def apply(self, raw: list[RawElement]) -> list[RawElement]:
        return [e for e in raw if e.visible and e.width > 0 and e.height > 0]
