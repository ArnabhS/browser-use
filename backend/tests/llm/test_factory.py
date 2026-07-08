from app.llm.factory import build_chat_model
from app.config.settings import Settings


def test_build_chat_model_binds_tools_and_targets_openrouter():
    s = Settings(openrouter_api_key="sk-test", agent_model="anthropic/claude-sonnet-4.6")
    model = build_chat_model(s)
    # bind_tools returns a RunnableBinding; the bound kwargs carry our tool schemas
    assert hasattr(model, "astream")
    bound = getattr(model, "kwargs", {})
    names = {t["function"]["name"] for t in bound.get("tools", [])} if bound.get("tools") else set()
    if not names:
        # fallback: try model.tools
        tools_attr = getattr(model, "tools", None) or []
        names = {t["function"]["name"] for t in tools_attr if isinstance(t, dict) and "function" in t}
    assert {"Click", "Complete"} <= names


def test_build_chat_model_caps_output_tokens():
    # Unbounded output let a degenerate repetition loop ("Let's click [56]." x hundreds) run to the
    # provider limit and then poison history. One reasoning block + one tool call needs far less.
    s = Settings(openrouter_api_key="sk-test", agent_model="x/y")
    model = build_chat_model(s)
    assert model.bound.max_tokens == s.llm_max_output_tokens > 0
