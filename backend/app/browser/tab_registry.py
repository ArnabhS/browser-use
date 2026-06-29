from __future__ import annotations

from typing import Any

# A Playwright Page (or any object with .is_closed()). Kept loose so the registry is
# trivially unit-testable with fakes — its one job is allocating stable tab ids.
Page = Any


class TabRegistry:
    """Allocates a STABLE per-session integer id to each open tab.

    The id is keyed by page identity and assigned once, monotonically — closing a tab
    never frees its id for reuse. This is what lets the agent refer to "tab 0" across
    turns even as the live `context.pages` order shifts under it.
    """

    def __init__(self) -> None:
        self._ids: dict[int, int] = {}        # id(page) -> stable tab id
        self._pages: dict[int, Page] = {}     # id(page) -> page (to prune closed ones)
        self._next = 0

    def register(self, page: Page) -> int:
        """Assign (or return the existing) stable id for `page`."""
        key = id(page)
        if key not in self._ids:
            self._ids[key] = self._next
            self._pages[key] = page
            self._next += 1
        return self._ids[key]

    def sync(self, pages: list[Page]) -> None:
        """Register any newly-seen pages and drop ones that have closed."""
        for p in pages:
            self.register(p)
        live = {id(p) for p in pages}
        for key in list(self._ids):
            if key not in live or self._pages[key].is_closed():
                del self._ids[key]
                del self._pages[key]

    def id_of(self, page: Page) -> int | None:
        return self._ids.get(id(page))

    def page_for(self, tab_id: int, pages: list[Page]) -> Page | None:
        """Resolve a stable id to one of the currently-live `pages`, or None."""
        for p in pages:
            if self._ids.get(id(p)) == tab_id:
                return p
        return None
