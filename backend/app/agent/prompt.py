from __future__ import annotations

from langchain_core.messages import SystemMessage

from app.agent.state import AgentState
from app.tools.specs import tool_descriptions

SYSTEM_PROMPT = """You are a web browser agent. Each turn you receive the current page as a \
numbered list of interactable elements. Think step by step in plain text FIRST, then call exactly \
one tool to act. Refer to elements by their [N] index. When the task is achieved (or impossible), \
call Complete(success, reason).

Available tools:
{tools}

Working memory:
{memory}
"""


def build_system_message(state: AgentState) -> SystemMessage:
    memory = "\n".join(f"- {k}: {v}" for k, v in state.agent_memory.items()) or "(empty)"
    return SystemMessage(content=SYSTEM_PROMPT.format(tools=tool_descriptions(), memory=memory))
