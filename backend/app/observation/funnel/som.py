from __future__ import annotations

from app.observation.raw import RawElement


class IndexedElement(RawElement):
    index: int
    center_x: float
    center_y: float


class SoMIndexer:
    """Assign a small integer [N] to each element and compute its click center."""

    def apply(self, raw: list[RawElement]) -> list[IndexedElement]:
        out: list[IndexedElement] = []
        for i, e in enumerate(raw, start=1):
            out.append(
                IndexedElement(
                    **e.model_dump(),
                    index=i,
                    center_x=e.x + e.width / 2,
                    center_y=e.y + e.height / 2,
                )
            )
        return out
