from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, BeforeValidator

# window.scrollY/scrollX (and viewport dims under zoom) come back as fractional pixels on
# hi-DPI / zoomed / very long pages (e.g. 10129.5). Round them so they satisfy an int field
# instead of crashing extraction mid-run.
RoundedInt = Annotated[
    int, BeforeValidator(lambda v: round(v) if isinstance(v, float) else v)
]


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
    viewport_width: RoundedInt
    viewport_height: RoundedInt
    scroll_x: RoundedInt = 0
    scroll_y: RoundedInt = 0
