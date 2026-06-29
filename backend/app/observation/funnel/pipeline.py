from __future__ import annotations

import logging

from browser_agent_contracts import Observation, Viewport

from app.observation.funnel.occlusion import OcclusionCuller
from app.observation.funnel.reading_order import ReadingOrderFormatter
from app.observation.funnel.som import SoMIndexer
from app.observation.funnel.trace import trace_funnel
from app.observation.funnel.visibility import VisibilityFilter
from app.observation.funnel.wrapper_collapse import WrapperCollapser
from app.observation.raw import PageMeta, RawElement

logger = logging.getLogger(__name__)


def run_funnel(
    raw: list[RawElement], meta: PageMeta, *, screenshot_ref: str | None = None,
    debug_focus: str | None = None,
) -> tuple[Observation, dict[int, tuple[float, float]], dict[int, tuple[float, float, float, float]]]:
    visible = VisibilityFilter().apply(raw)
    unoccluded = OcclusionCuller().apply(visible)
    collapsed = WrapperCollapser().apply(unoccluded)
    indexed = SoMIndexer().apply(collapsed)
    center_map = {e.index: (e.center_x, e.center_y) for e in indexed}
    box_map = {e.index: (e.x, e.y, e.width, e.height) for e in indexed}
    elements, dropped = ReadingOrderFormatter().apply(indexed)
    shown = {e.index for e in elements}
    index_map = {i: c for i, c in center_map.items() if i in shown}
    index_boxes = {i: b for i, b in box_map.items() if i in shown}
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
    if debug_focus:
        lines = trace_funnel(
            [("extract", raw), ("visibility", visible), ("occlusion", unoccluded),
             ("wrapper_collapse", collapsed), ("indexed", indexed)],
            focus=debug_focus,
        )
        f = debug_focus.lower()
        final = [e for e in elements if f in (e.name or "").lower()]
        lines.append(
            f"[funnel] reading_order(shown): {len(elements)} elements | "
            f"focus '{debug_focus}': {len(final)} | dropped(budget)={dropped}"
        )
        logger.warning("funnel trace for %s\n%s", meta.url, "\n".join(lines))
    return observation, index_map, index_boxes
