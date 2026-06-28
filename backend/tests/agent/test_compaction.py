# backend/tests/agent/test_compaction.py
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from app.agent.compaction import compact_for_llm


def _obs(text):  # an observation message as the observe node will tag it
    return HumanMessage(content=text, name="observation")


def test_drops_all_but_the_latest_observation():
    msgs = [
        _obs("page 1 [0] a [1] b"),
        AIMessage(content="click", tool_calls=[{"name": "Click", "args": {"index": 1}, "id": "t1"}]),
        ToolMessage(content="ok", tool_call_id="t1", name="Click"),
        _obs("page 2 [0] c [1] d"),
    ]
    out, status = compact_for_llm(msgs)
    obs = [m for m in out if isinstance(m, HumanMessage) and m.name == "observation"]
    assert len(obs) == 1 and "page 2" in obs[0].content   # only the freshest observation kept
    assert status["dropped_observations"] == 1
    # the action trail (AI tool call + its ToolMessage) is preserved
    assert any(isinstance(m, AIMessage) and m.tool_calls for m in out)
    assert any(isinstance(m, ToolMessage) and m.tool_call_id == "t1" for m in out)


def test_truncates_old_tool_output_but_not_the_current_turn():
    big = "x" * 5000
    msgs = [
        _obs("page 1"),
        AIMessage(content="", tool_calls=[{"name": "Extract", "args": {}, "id": "t1"}]),
        ToolMessage(content=big, tool_call_id="t1", name="Extract"),   # 2 obs ago -> truncate
        _obs("page 2"),
        AIMessage(content="", tool_calls=[{"name": "Extract", "args": {}, "id": "t2"}]),
        ToolMessage(content=big, tool_call_id="t2", name="Extract"),   # current turn -> keep full
        _obs("page 3"),
    ]
    out, status = compact_for_llm(msgs, max_tool_chars=2000)
    tool_contents = [m.content for m in out if isinstance(m, ToolMessage)]
    assert any(len(c) < 2100 and "truncated" in c for c in tool_contents)   # old one truncated
    assert any(len(c) == 5000 for c in tool_contents)                       # current-turn one intact
    assert status["truncated_tools"] == 1
    assert status["dropped_observations"] == 2


def test_no_observations_is_a_noop():
    msgs = [AIMessage(content="hi"), HumanMessage(content="not an observation")]
    out, status = compact_for_llm(msgs)
    assert out == msgs and status["dropped_observations"] == 0
