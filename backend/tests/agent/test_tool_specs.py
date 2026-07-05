from app.tools.specs import TOOL_SPECS, tool_descriptions, Click, Complete, AskUser


def test_specs_have_expected_names():
    names = {s.__name__ for s in TOOL_SPECS}
    assert names == {
        "Navigate", "Click", "LongPress", "TypeText", "Scroll", "Extract", "SearchPage",
        "FindElements", "WaitFor",
        "PressKey", "Clear", "SelectOption", "NewTab", "SwitchTab", "CloseTab",
        "ObserveTab", "OpenInNewTab",
        "Remember", "Recall", "SetPlan", "AskUser", "Complete",
    }
    assert len(names) == 22


def test_ask_user_spec():
    assert AskUser(question="x").question == "x"


def test_new_tool_fields():
    from app.tools.specs import PressKey, SelectOption, SwitchTab
    assert PressKey(key="Enter").key == "Enter"
    assert SelectOption(index=2, value="US").value == "US"
    assert SwitchTab(target_id="1").target_id == "1"


def test_click_schema_fields():
    c = Click(index=5)
    assert c.index == 5
    assert Complete(success=True, reason="done").success is True


def test_tool_descriptions_render_one_line_per_tool():
    text = tool_descriptions()
    assert "- Click(index): " in text
    assert "- Complete(success, reason): " in text
    assert text.count("\n- ") + 1 == len(TOOL_SPECS)  # one bullet per tool
