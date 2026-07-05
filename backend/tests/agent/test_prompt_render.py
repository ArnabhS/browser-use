from app.agent.prompt import build_memory_message, render_system_text
from app.agent.state import AgentState


def test_system_message_contains_tools_and_reasoning_rule():
    text = render_system_text(AgentState(task="log in", thread_id="t1"))
    assert "Click(index)" in text            # tool descriptions rendered
    assert "reason" in text.lower() and "tool" in text.lower()  # think-before-act guidance
    assert "log in" in text                   # task rendered


def test_working_memory_renders_outside_the_cached_system_prompt():
    state = AgentState(task="log in", thread_id="t1", agent_memory={"url": "/auth"})
    assert "url: /auth" not in render_system_text(state)          # not in the cached prefix
    assert "url: /auth" in build_memory_message(state).content    # surfaced separately


def test_system_message_uses_custom_resolver_override():
    from app.prompt.resolver import PromptResolver

    state = AgentState(task="T", thread_id="t1")
    r = PromptResolver({"agent_system": "OVERRIDE task={{ task }} tools={{ tool_descriptions }}"})
    text = render_system_text(state, resolver=r)
    assert text.startswith("OVERRIDE task=T")
    assert "Click(index)" in text
