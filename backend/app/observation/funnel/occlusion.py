from __future__ import annotations

from app.observation.raw import RawElement


class OcclusionCuller:
    """Drop elements whose click center is covered by an unrelated element on top."""

    def apply(self, raw: list[RawElement]) -> list[RawElement]:
        return [e for e in raw if not e.occluded]
