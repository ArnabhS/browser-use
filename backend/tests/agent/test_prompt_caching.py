"""P0-1 OpenRouter prompt caching. The stable system-prompt + tool-schema prefix must be a single
cache-marked block so OpenRouter caches it across turns; working memory (which grows as the agent
calls Remember) must live OUTSIDE that block, else its changing bytes bust the cache every step."""
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.prompt import build_memory_message, build_system_message, render_system_text
from app.agent.state import AgentState


def _blocks(msg: SystemMessage) -> list[dict]:
    assert isinstance(msg.content, list), "system content must be a block list to carry cache_control"
    return msg.content


def test_system_message_last_block_is_cache_marked_for_anthropic():
    msg = build_system_message(AgentState(task="log in", thread_id="t1"), model="anthropic/claude-sonnet-4.6")
    blocks = _blocks(msg)
    assert blocks[-1]["cache_control"] == {"type": "ephemeral"}
    # exactly one breakpoint — Anthropic allows ≤4 but we only need the one prefix boundary
    assert sum("cache_control" in b for b in blocks) == 1


def test_system_message_is_plain_string_for_non_anthropic():
    # A stray cache_control block can trip a non-Anthropic provider via OpenRouter; emit plain text.
    msg = build_system_message(AgentState(task="log in", thread_id="t1"), model="google/gemini-3.5-flash")
    assert isinstance(msg.content, str)
    assert "Click(index)" in msg.content


def test_memory_is_not_inside_the_cached_system_block():
    # Memory changing must not change the cached prefix bytes.
    state = AgentState(task="log in", thread_id="t1", agent_memory={"url": "/auth"})
    text = render_system_text(state)
    assert "/auth" not in text and "url: /auth" not in text
    # The stable instructions + task ARE still in the cached prefix.
    assert "Click(index)" in text and "log in" in text


def test_cached_prefix_is_stable_as_memory_grows():
    a = render_system_text(AgentState(task="T", thread_id="t1", agent_memory={}))
    b = render_system_text(AgentState(task="T", thread_id="t1", agent_memory={"k": "v", "k2": "v2"}))
    assert a == b, "system prefix must be byte-identical regardless of working memory"


def test_memory_message_renders_memory_when_present():
    msg = build_memory_message(AgentState(task="T", thread_id="t1", agent_memory={"url": "/auth"}))
    assert isinstance(msg, HumanMessage)
    assert "url: /auth" in msg.content


def test_memory_message_is_none_when_empty():
    assert build_memory_message(AgentState(task="T", thread_id="t1", agent_memory={})) is None
