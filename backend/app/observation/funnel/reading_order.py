from __future__ import annotations

from browser_agent_contracts import Element

from app.observation.funnel.som import IndexedElement

_ROW_TOLERANCE = 12.0  # px: elements within this vertical band count as the same row


class ReadingOrderFormatter:
    """Serialize indexed elements in visual reading order, within a budget."""

    def __init__(self, max_elements: int = 120) -> None:
        self._max = max_elements

    def apply(self, indexed: list[IndexedElement]) -> tuple[list[Element], int]:
        # Budget: prefer in-viewport elements; drop off-screen first.
        dropped = 0
        kept = indexed
        if len(indexed) > self._max:
            in_vp = [e for e in indexed if e.in_viewport]
            off = [e for e in indexed if not e.in_viewport]
            kept = (in_vp + off)[: self._max]
            dropped = len(indexed) - len(kept)

        # Reading order: bucket by row (y within tolerance), then sort rows top→down, items left→right.
        ordered = sorted(kept, key=lambda e: (round(e.y / _ROW_TOLERANCE), e.x))
        elements = [
            Element(index=e.index, role=e.role, name=e.name, value=e.value) for e in ordered
        ]
        return elements, dropped
