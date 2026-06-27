from app.agent.state import AgentState
from app.agent.prompt import build_system_message


def test_system_message_contains_tools_memory_and_reasoning_rule():
    state = AgentState(task="log in", thread_id="t1", agent_memory={"url": "/auth"})
    msg = build_system_message(state)
    text = msg.content
    assert "Click(index)" in text            # tool descriptions rendered
    assert "url: /auth" in text               # memory block rendered
    assert "reason" in text.lower() and "tool" in text.lower()  # think-before-act guidance
    assert "log in" in text                   # task rendered
