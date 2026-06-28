from __future__ import annotations

from app.config.settings import Settings
from app.tools.specs import TOOL_SPECS


def build_chat_model(settings: Settings):
    """A bind_tools'd ChatOpenAI Runnable pointed at OpenRouter."""
    from langchain_openai import ChatOpenAI

    model = ChatOpenAI(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        model=settings.agent_model,
        temperature=settings.llm_temperature,
        stream_usage=True,
        max_retries=0,  # OpenRouterLLMClient owns retries
    )
    # Browser agent: ONE action per turn — the page mutates and SoM indices are rebuilt every observe(),
    # so batching effect actions against a single index_map would click stale coordinates.
    return model.bind_tools(TOOL_SPECS, parallel_tool_calls=False)
