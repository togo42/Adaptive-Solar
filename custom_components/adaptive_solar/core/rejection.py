"""Bounded, JSON-safe views of decisions, never a second acceptance policy."""
from __future__ import annotations

from datetime import datetime, timezone

DETAIL_LIMIT = 50


def detail_time(value) -> str | None:
    """Only real, timezone-aware original times; no fallback to wall time."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    try:
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    except (ValueError, OverflowError):
        return None


class RejectionDetails:
    """Keep at most 50 unique keys while counting every original rejection.

    UTC strings have fixed precision, so lexical order is chronological. All
    tie-breakers descend (end, start, issue, regime); unknown times come last.
    A key evicted from the newest 50 can never re-enter later in this stream.
    """

    def __init__(self) -> None:
        self.total = 0
        self._items: dict[tuple, set[str]] = {}

    def add(self, start, end, reasons, *, issued_at=None, regime=None) -> None:
        self.total += 1
        key = (detail_time(end), detail_time(start))
        if regime is not None:
            key += (detail_time(issued_at), regime)
        if key in self._items:
            self._items[key].update(reasons)
            return
        if len(self._items) == DETAIL_LIMIT:
            oldest = min(self._items, key=self._order)
            if self._order(key) <= self._order(oldest):
                return
            del self._items[oldest]
        self._items[key] = set(reasons)

    @staticmethod
    def _order(key):
        return tuple(value or "" for value in key)

    def to_dict(self) -> dict:
        items = []
        for key in sorted(self._items, key=self._order, reverse=True):
            end, start, *extra = key
            item = {"start": start, "end": end, "reasons": sorted(self._items[key])}
            if extra:
                item.update(issued_at=extra[0], regime=extra[1])
            items.append(item)
        return {"total": self.total, "truncated": self.total > len(items), "items": items}
