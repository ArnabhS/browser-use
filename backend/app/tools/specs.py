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
    """Scroll the page up or down by `amount` viewport steps."""
    direction: Literal["up", "down"]
    amount: int = 1


class Extract(BaseModel):
    """Read text/answer a question from the current page without acting."""
    query: str


class WaitFor(BaseModel):
    """Wait for the page to settle for `seconds` before re-observing."""
    seconds: float = 1.0


class Remember(BaseModel):
    """Save a durable key/value note to working memory for later steps."""
    key: str
    value: str


class Recall(BaseModel):
    """Return everything currently in working memory."""


class SetPlan(BaseModel):
    """Set or replace the step-by-step plan shown to the user."""
    steps: list[str]


class Complete(BaseModel):
    """Finish the task. success=True if the goal was achieved, with a short reason."""
    success: bool
    reason: str


TOOL_SPECS: list[type[BaseModel]] = [
    Navigate, Click, TypeText, Scroll, Extract,
    WaitFor, Remember, Recall, SetPlan, Complete,
]

BROWSER_TOOLS = {"Navigate", "Click", "TypeText", "Scroll", "Extract", "WaitFor"}
MEMORY_TOOLS = {"Remember", "Recall"}
CONTROL_TOOLS = {"SetPlan", "Complete"}


def tool_descriptions() -> str:
    """Render `- Name(arg1, arg2): <docstring first line>` for each tool spec."""
    lines: list[str] = []
    for spec in TOOL_SPECS:
        args = ", ".join(spec.model_fields.keys())
        doc = (spec.__doc__ or "").strip().splitlines()[0] if spec.__doc__ else ""
        lines.append(f"- {spec.__name__}({args}): {doc}")
    return "\n".join(lines)
