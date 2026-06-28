from __future__ import annotations

from pydantic import BaseModel


class RawElement(BaseModel):
    tag: str
    role: str
    name: str = ""
    value: str | None = None
    x: float
    y: float
    width: float
    height: float
    visible: bool = True
    in_viewport: bool = True
    occluded: bool = False


class PageMeta(BaseModel):
    url: str
    title: str = ""
    viewport_width: int
    viewport_height: int
    scroll_x: int = 0
    scroll_y: int = 0
