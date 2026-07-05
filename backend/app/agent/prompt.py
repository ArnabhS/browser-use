from __future__ import annotations

from datetime import date

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.state import AgentState
from app.config.settings import get_settings
from app.prompt.loader import PromptLoader, default_loader
from app.prompt.resolver import PromptResolver
from app.tools.specs import tool_descriptions

_SYSTEM_TEMPLATE = "agent/system.jinja2"
# Anthropic-via-OpenRouter caches the message prefix up to an explicit ephemeral breakpoint (and only
# then — it is NOT automatic for Anthropic). One breakpoint on the last system block caches the whole
# stable prefix (instructions + bound tool schema + the run-constant task) at 0.25x on later turns.
_CACHE_CONTROL = {"type": "ephemeral"}


def render_system_text(
    state: AgentState,
    *,
    loader: PromptLoader | None = None,
    resolver: PromptResolver | None = None,
) -> str:
    """The STABLE system-prompt text — instructions + tool descriptions + the run-constant task.

    Deliberately excludes working memory: memory grows as the agent calls Remember, and any changing
    bytes inside the cached block would bust the cache every step (it moves to build_memory_message).
    """
    loader = loader or default_loader()
    # The agent has no innate sense of "now" — without it, "upcoming"/"recent"/date-filter tasks
    # search the wrong year (a benchmark trace had it hunting 2025 events in mid-2026). Constant per
    # run, so it stays in the cacheable prefix.
    ctx = {"tool_descriptions": tool_descriptions(), "task": state.task, "today": date.today().isoformat()}
    if resolver is not None:
        return resolver.render("agent_system", ctx, loader, fallback=_SYSTEM_TEMPLATE)
    return loader.render(_SYSTEM_TEMPLATE, ctx)


def _wants_cache_control(model: str) -> bool:
    """OpenRouter honors explicit `cache_control` breakpoints only for Anthropic (and it's the family
    that isn't auto-cached). For everyone else, emit a plain-string system prompt — a stray
    cache_control block can confuse a non-Anthropic provider and buys nothing."""
    m = model.lower()
    return "claude" in m or m.startswith("anthropic")


def build_system_message(
    state: AgentState,
    *,
    loader: PromptLoader | None = None,
    resolver: PromptResolver | None = None,
    model: str | None = None,
) -> SystemMessage:
    """The system message. For Anthropic models it's a single cache-marked block so OpenRouter caches
    the fixed prefix; for other models it's a plain string (no stray caching markers)."""
    text = render_system_text(state, loader=loader, resolver=resolver)
    model = model if model is not None else get_settings().agent_model
    if _wants_cache_control(model):
        return SystemMessage(content=[{"type": "text", "text": text, "cache_control": _CACHE_CONTROL}])
    return SystemMessage(content=text)


def build_memory_message(state: AgentState) -> HumanMessage | None:
    """Working memory as its own message AFTER the cached system block (empty → no message).

    Kept out of the cached prefix on purpose (see render_system_text); OpenRouter's own guidance is to
    move dynamic content into a later message rather than append it inside the cached system block.
    """
    if not state.agent_memory:
        return None
    memory = "\n".join(f"- {k}: {v}" for k, v in state.agent_memory.items())
    return HumanMessage(content=f"Working memory:\n{memory}", name="working_memory")
