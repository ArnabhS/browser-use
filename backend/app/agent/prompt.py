from __future__ import annotations

from langchain_core.messages import SystemMessage

from app.agent.state import AgentState
from app.prompt.loader import PromptLoader, default_loader
from app.prompt.resolver import PromptResolver
from app.tools.specs import tool_descriptions

_SYSTEM_TEMPLATE = "agent/system.jinja2"


def build_system_message(
    state: AgentState,
    *,
    loader: PromptLoader | None = None,
    resolver: PromptResolver | None = None,
) -> SystemMessage:
    loader = loader or default_loader()
    memory = "\n".join(f"- {k}: {v}" for k, v in state.agent_memory.items()) or "(empty)"
    ctx = {"tool_descriptions": tool_descriptions(), "memory": memory, "task": state.task}
    if resolver is not None:
        text = resolver.render("agent_system", ctx, loader, fallback=_SYSTEM_TEMPLATE)
    else:
        text = loader.render(_SYSTEM_TEMPLATE, ctx)
    return SystemMessage(content=text)
