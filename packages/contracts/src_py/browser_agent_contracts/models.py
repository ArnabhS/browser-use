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
    index: int
    role: str
    name: str = ""
    value: str | None = None


class Observation(BaseModel):
    model_config = _CAMEL
    protocol_version: str = Field(default=PROTOCOL_VERSION, alias="protocolVersion")
    url: str
    title: str = ""
    viewport: Viewport
    elements: list[Element] = Field(default_factory=list)
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
    payload: dict[str, Any] = Field(default_factory=dict)
