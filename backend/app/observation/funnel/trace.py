from __future__ import annotations

from app.observation.raw import RawElement


def _descriptor(e: RawElement) -> str:
    return (
        f'{e.tag}<{e.role}> "{(e.name or "")[:40]}" '
        f"@({int(e.x)},{int(e.y)} {int(e.width)}x{int(e.height)}) "
        f"vis={e.visible} inVp={e.in_viewport} occ={e.occluded}"
    )


def _key(e: RawElement) -> tuple:
    return (e.tag, e.role, e.name, round(e.x), round(e.y))


def trace_funnel(named_stages: list[tuple[str, list[RawElement]]], focus: str) -> list[str]:
    """Per-stage report of the funnel, highlighting elements whose name matches `focus`.

    Returns log lines showing, for each stage: the element count, how many focus-matches
    survived, the full descriptor of each survivor, and — crucially — a `DROPPED at <stage>`
    line for any focus-match that was present in the previous stage but gone in this one.
    This is what tells you whether a "can see it but can't click it" element was never
    extracted (focus count 0 from the start) or extracted then culled (and by which stage).
    """
    f = (focus or "").lower()
    lines: list[str] = []
    prev_keys: set | None = None
    for name, els in named_stages:
        matches = [e for e in els if f and f in (e.name or "").lower()]
        lines.append(f"[funnel] {name}: {len(els)} elements | focus '{focus}': {len(matches)}")
        for m in matches:
            lines.append(f"    keep {_descriptor(m)}")
        keys = {_key(e) for e in matches}
        if prev_keys is not None:
            for tag, role, nm, _x, _y in prev_keys - keys:
                lines.append(f'    >>> DROPPED at {name}: {tag}<{role}> "{(nm or "")[:40]}"')
        prev_keys = keys
    return lines
