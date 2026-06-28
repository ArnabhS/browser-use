# backend/app/memory/document.py
"""Pure functions for the agent's MEMORY.md document. No I/O, no LLM."""
from __future__ import annotations

import re

_KNOWLEDGE_RE = re.compile(r"^- \*\*(?P<key>.+?)\*\*: (?P<value>.*)$")


def build_document(knowledge: dict[str, str], runs: list[str]) -> str:
    lines = ["# Agent Memory", "", "## Knowledge"]
    lines += [f"- **{k}**: {v}" for k, v in knowledge.items()]
    lines += ["", "## Run History"]
    lines += [f"- {r}" for r in runs]
    return "\n".join(lines) + "\n"


def parse_knowledge(md: str) -> dict[str, str]:
    out: dict[str, str] = {}
    in_knowledge = False
    for line in md.splitlines():
        if line.strip() == "## Knowledge":
            in_knowledge = True
            continue
        if line.startswith("## ") and line.strip() != "## Knowledge":
            in_knowledge = False
            continue
        if in_knowledge:
            m = _KNOWLEDGE_RE.match(line)
            if m:
                out[m.group("key")] = m.group("value")
    return out


def _runs(md: str) -> list[str]:
    runs: list[str] = []
    in_runs = False
    for line in md.splitlines():
        if line.strip() == "## Run History":
            in_runs = True
            continue
        if line.startswith("## ") and line.strip() != "## Run History":
            in_runs = False
            continue
        if in_runs and line.startswith("- "):
            runs.append(line[2:])
    return runs


def update_knowledge(md: str, key: str, value: str) -> str:
    knowledge = parse_knowledge(md)
    knowledge[key] = value
    return build_document(knowledge, _runs(md))


def append_run(md: str, run_summary: str, *, max_runs: int = 20) -> str:
    runs = _runs(md)
    runs.append(run_summary)
    runs = runs[-max_runs:]
    return build_document(parse_knowledge(md), runs)
