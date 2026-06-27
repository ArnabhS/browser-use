from app.tools.specs import TOOL_SPECS, tool_descriptions, Click, Complete


def test_specs_have_expected_names():
    names = {s.__name__ for s in TOOL_SPECS}
    assert names == {
        "Navigate", "Click", "TypeText", "Scroll", "Extract",
        "WaitFor", "Remember", "Recall", "SetPlan", "Complete",
    }


def test_click_schema_fields():
    c = Click(index=5)
    assert c.index == 5
    assert Complete(success=True, reason="done").success is True


def test_tool_descriptions_render_one_line_per_tool():
    text = tool_descriptions()
    assert "- Click(index): " in text
    assert "- Complete(success, reason): " in text
    assert text.count("\n- ") + 1 == len(TOOL_SPECS)  # one bullet per tool
