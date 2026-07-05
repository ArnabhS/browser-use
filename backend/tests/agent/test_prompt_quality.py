"""The system prompt must actually coach the agent — perception, a reasoning scaffold,
completion discipline, and when to ask the human — not just dump rules and tools."""
from app.agent.prompt import render_system_text
from app.agent.state import AgentState


def _text(task: str = "buy a hat") -> str:
    return render_system_text(AgentState(task=task, thread_id="t1"))


def test_prompt_frames_perception_and_one_action_per_turn():
    low = _text().lower()
    assert "screenshot" in low                                   # vision is named, not silent
    assert "one" in low or "single" in low                       # one action per turn
    assert "index" in low and ("current" in low or "every turn" in low)  # per-turn indices


def test_prompt_has_completion_criteria_and_forbids_fabrication():
    low = _text().lower()
    assert "complete(" in low
    assert "evidence" in low                                     # cite what's on screen
    assert any(w in low for w in ("make up", "fabricate", "invent"))


def test_prompt_tells_agent_to_ask_user_when_blocked():
    text = _text()
    assert "AskUser" in text
    low = text.lower()
    assert any(w in low for w in ("otp", "credential", "captcha"))


def test_prompt_scaffolds_reasoning_about_the_last_action():
    low = _text().lower()
    assert "reasoning" in low
    assert "last action" in low or "did the page change" in low or "assess" in low


def test_prompt_says_engine_auto_settles_so_no_routine_waitfor():
    # The engine already waits for load + settle after every action, so routine WaitFor calls are
    # wasted turns. The prompt must say so, or the agent burns 5s/turn "letting the page load".
    low = _text().lower()
    assert "waitfor" in low
    assert "already" in low and ("settle" in low or "loaded" in low or "finish loading" in low)
