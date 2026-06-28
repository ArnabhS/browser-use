# backend/app/agent/compaction.py
"""Layer 0+1 context compaction: drop superseded observations, truncate old tool outputs.

Old observations carry STALE element indices (the agent must act only on the freshest
observation — CLAUDE.md §3), so dropping them is both a token win and a correctness guard.
Layer 2 (LLM-summarize) is intentionally not here — it is a deferred fast-follow."""
from __future__ import annotations

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage


def _is_observation(m: BaseMessage) -> bool:
    return isinstance(m, HumanMessage) and getattr(m, "name", None) == "observation"


def compact_for_llm(
    messages: list[BaseMessage], *, max_tool_chars: int = 2000
) -> tuple[list[BaseMessage], dict]:
    obs_idxs = [i for i, m in enumerate(messages) if _is_observation(m)]
    keep_obs = set(obs_idxs[-1:])
    # Truncate tool outputs OLDER than the second-to-last observation; the freshest
    # action's output sits between the last two observations and must stay intact
    # (graph order act->observe->reason puts every tool msg before the latest obs).
    trunc_before = obs_idxs[-2] if len(obs_idxs) >= 2 else -1

    out: list[BaseMessage] = []
    dropped = truncated = 0
    for i, m in enumerate(messages):
        if _is_observation(m) and i not in keep_obs:
            dropped += 1
            continue
        if (
            isinstance(m, ToolMessage)
            and i < trunc_before
            and isinstance(m.content, str)
            and len(m.content) > max_tool_chars
        ):
            out.append(
                ToolMessage(
                    content=m.content[:max_tool_chars] + " …[truncated]",
                    tool_call_id=m.tool_call_id,
                    name=m.name,
                    status=m.status,
                    additional_kwargs=m.additional_kwargs,
                )
            )
            truncated += 1
            continue
        out.append(m)

    status = {
        "messages_in": len(messages),
        "messages_out": len(out),
        "dropped_observations": dropped,
        "truncated_tools": truncated,
    }
    return out, status
