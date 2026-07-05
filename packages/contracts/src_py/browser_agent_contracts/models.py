from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .version import PROTOCOL_VERSION

_CAMEL = ConfigDict(populate_by_name=True)


class Viewport(BaseModel):
    model_config = _CAMEL
    width: int
    height: int
    scroll_x: int = Field(default=0, alias="scrollX")
    scroll_y: int = Field(default=0, alias="scrollY")


class Element(BaseModel):
    model_config = _CAMEL
    index: int
    role: str
    name: str = ""
    value: str | None = None
    # True when this element was not present in the previous turn's observation (same page) — i.e. it
    # appeared as a result of the agent's last action (a dropdown, modal, autocomplete list…).
    is_new: bool = Field(default=False, alias="isNew")


class Tab(BaseModel):
    """One open browser tab. `id` is a stable per-session integer the agent uses to
    SwitchTab/CloseTab — it is NOT a positional index and never gets reused."""
    id: int
    title: str = ""
    url: str = ""
    active: bool = False


class Observation(BaseModel):
    model_config = _CAMEL
    protocol_version: str = Field(default=PROTOCOL_VERSION, alias="protocolVersion")
    url: str
    title: str = ""
    viewport: Viewport
    elements: list[Element] = Field(default_factory=list)
    tabs: list[Tab] = Field(default_factory=list)
    screenshot_ref: str | None = Field(default=None, alias="screenshotRef")
    changed: str | None = None
    dropped_count: int = Field(default=0, alias="droppedCount")


class ActionCall(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ActionResult(BaseModel):
    model_config = _CAMEL
    success: bool
    reason: str = ""
    error_code: str | None = Field(default=None, alias="errorCode")


class Envelope(BaseModel):
    model_config = _CAMEL
    protocol_version: str = Field(default=PROTOCOL_VERSION, alias="protocolVersion")
    type: str
    # Correlation id for request/response over the bridge relay: a request carries an `id` and its
    # response echoes the same one. Optional so unsolicited messages (frame, register) can omit it.
    id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
