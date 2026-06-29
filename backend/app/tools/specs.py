from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Navigate(BaseModel):
    """Navigate the active tab to a URL."""
    url: str = Field(description="Absolute URL to open")


class Click(BaseModel):
    """Click the element with the given [N] index from the current observation."""
    index: int = Field(description="The element index to click")


class TypeText(BaseModel):
    """Type text into the element with the given index."""
    index: int
    text: str


class Scroll(BaseModel):
    """Scroll up or down by `amount` viewport-heights. Set `index` to scroll the scrollable box that element sits in (a modal, chat pane, or inner list) instead of the whole page."""
    direction: Literal["up", "down"]
    amount: int = 1
    index: int | None = None


class Extract(BaseModel):
    """Read text/answer a question from the current page without acting."""
    query: str


class WaitFor(BaseModel):
    """Wait for the page to settle for `seconds` before re-observing."""
    seconds: float = 1.0


class PressKey(BaseModel):
    """Press a single key or chord (e.g. 'Enter', 'Tab', 'Escape') — use after typing to submit."""
    key: str


class Clear(BaseModel):
    """Clear the text in the input element with the given index before typing fresh text."""
    index: int


class SelectOption(BaseModel):
    """Choose an option (by visible text or value) in the dropdown <select> at the given index."""
    index: int
    value: str


class NewTab(BaseModel):
    """Open a new browser tab at the given URL and switch to it."""
    url: str


class SwitchTab(BaseModel):
    """Switch the active tab to the tab with the given id (the [N] shown under 'Open tabs')."""
    target_id: str


class CloseTab(BaseModel):
    """Close the tab with the given id (the [N] shown under 'Open tabs')."""
    target_id: str


class ObserveTab(BaseModel):
    """Read another tab's title + URL WITHOUT switching to it — to decide whether it's the one you want before SwitchTab."""
    target_id: str


class OpenInNewTab(BaseModel):
    """Open the link at the given element index in a NEW background tab, staying on the current tab. Use to queue several results (e.g. products) then SwitchTab to compare them."""
    index: int


class Remember(BaseModel):
    """Save a durable key/value note to working memory for later steps."""
    key: str
    value: str


class Recall(BaseModel):
    """Return everything currently in working memory."""


class SetPlan(BaseModel):
    """Set or replace the step-by-step plan shown to the user."""
    steps: list[str]


class AskUser(BaseModel):
    """Ask the human operator for information you cannot get yourself — login credentials, an OTP/2FA code, a CAPTCHA answer, or a clarification. The run PAUSES until they reply, then their answer is returned to you. Use sparingly, only when truly blocked."""
    question: str
    context: str = ""


class Complete(BaseModel):
    """Finish the task. success=True if the goal was achieved, with a short reason."""
    success: bool
    reason: str


TOOL_SPECS: list[type[BaseModel]] = [
    Navigate, Click, TypeText, Scroll, Extract, WaitFor,
    PressKey, Clear, SelectOption, NewTab, SwitchTab, CloseTab, ObserveTab, OpenInNewTab,
    Remember, Recall, SetPlan, AskUser, Complete,
]

BROWSER_TOOLS = {"Navigate", "Click", "TypeText", "Scroll", "Extract", "WaitFor",
                 "PressKey", "Clear", "SelectOption", "NewTab", "SwitchTab", "CloseTab",
                 "ObserveTab", "OpenInNewTab"}
MEMORY_TOOLS = {"Remember", "Recall"}
CONTROL_TOOLS = {"SetPlan", "Complete", "AskUser"}


def tool_descriptions() -> str:
    """Render `- Name(arg1, arg2): <docstring first line>` for each tool spec."""
    lines: list[str] = []
    for spec in TOOL_SPECS:
        args = ", ".join(spec.model_fields.keys())
        doc = (spec.__doc__ or "").strip().splitlines()[0] if spec.__doc__ else ""
        lines.append(f"- {spec.__name__}({args}): {doc}")
    return "\n".join(lines)
