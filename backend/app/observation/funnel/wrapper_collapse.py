from __future__ import annotations

from app.observation.raw import RawElement

_REAL_TAGS = ("a", "button", "input", "select", "textarea", "summary")


class WrapperCollapser:
    """Collapse near-identical-bounds wrapper chains to one representative element."""

    def __init__(self, tol: float = 4.0) -> None:
        self._tol = tol

    def _key(self, e: RawElement) -> tuple:
        t = self._tol
        return (int(e.x // t), int(e.y // t), int(e.width // t), int(e.height // t))

    def apply(self, raw: list[RawElement]) -> list[RawElement]:
        groups: dict[tuple, list[RawElement]] = {}
        order: list[tuple] = []
        for e in raw:
            k = self._key(e)
            if k not in groups:
                groups[k] = []
                order.append(k)
            groups[k].append(e)

        out: list[RawElement] = []
        for k in order:
            members = groups[k]
            real = [m for m in members if m.tag in _REAL_TAGS]
            best = real[0] if real else members[0]
            # prefer a representative that actually has a name, if present
            named = [m for m in (real or members) if m.name]
            out.append(named[0] if named else best)
        return out
