from __future__ import annotations

from browser_agent_contracts import Observation


def format_observation(obs: Observation) -> str:
    """Render the compact, numbered element list the model reads each turn."""
    header = f"Current page: {obs.url}"
    if obs.title:
        header += f" — {obs.title}"
    lines = [header, "Interactable elements:"]
    for el in obs.elements:
        label = f"[{el.index}] {el.role}"
        if el.name:
            label += f' "{el.name}"'
        if el.value:
            label += f" = {el.value!r}"
        lines.append(label)
    if not obs.elements:
        lines.append("(none)")
    if obs.dropped_count:
        lines.append(f"({obs.dropped_count} lower-priority elements hidden — scroll to reveal)")
    if len(obs.tabs) > 1:
        lines.append("Open tabs:")
        for tab in obs.tabs:
            row = f'[{tab.id}] "{tab.title}"' if tab.title else f"[{tab.id}]"
            if tab.url:
                row += f" — {tab.url}"
            if tab.active:
                row += " (active)"
            lines.append(row)
    return "\n".join(lines)
