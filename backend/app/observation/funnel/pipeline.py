from __future__ import annotations

from browser_agent_contracts import Observation, Viewport

from app.observation.funnel.occlusion import OcclusionCuller
from app.observation.funnel.reading_order import ReadingOrderFormatter
from app.observation.funnel.som import SoMIndexer
from app.observation.funnel.visibility import VisibilityFilter
from app.observation.funnel.wrapper_collapse import WrapperCollapser
from app.observation.raw import PageMeta, RawElement


def run_funnel(
    raw: list[RawElement], meta: PageMeta, *, screenshot_ref: str | None = None
) -> tuple[Observation, dict[int, tuple[float, float]]]:
    visible = VisibilityFilter().apply(raw)
    unoccluded = OcclusionCuller().apply(visible)
    collapsed = WrapperCollapser().apply(unoccluded)
    indexed = SoMIndexer().apply(collapsed)
    index_map = {e.index: (e.center_x, e.center_y) for e in indexed}
    elements, dropped = ReadingOrderFormatter().apply(indexed)
    index_map = {e.index: index_map[e.index] for e in elements}
    observation = Observation(
        url=meta.url,
        title=meta.title,
        viewport=Viewport(
            width=meta.viewport_width, height=meta.viewport_height,
            scrollX=meta.scroll_x, scrollY=meta.scroll_y,
        ),
        elements=elements,
        screenshotRef=screenshot_ref,
        droppedCount=dropped,
    )
    return observation, index_map
