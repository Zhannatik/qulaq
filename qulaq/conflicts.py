"""Find events that cannot both be attended."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .events import Event

DEFAULT_DURATION = timedelta(hours=1)


@dataclass
class Conflict:
    first: Event
    second: Event
    reason: str


def _span(ev: Event) -> tuple[datetime, datetime] | None:
    if not ev.date or not ev.time:
        return None
    h, m = (int(x) for x in ev.time.split(":"))
    start = datetime(ev.date.year, ev.date.month, ev.date.day, h, m)
    return start, start + DEFAULT_DURATION


def find_conflicts(events: list[Event], *, busy: list[tuple[datetime, datetime, str]] | None = None) -> list[Conflict]:
    """Two timed events that overlap, or a timed event that overlaps a busy slot you give
    (for example a work meeting). Events without a time are never reported here."""
    timed = [(e, s) for e in events if (s := _span(e))]
    found: list[Conflict] = []
    for i, (a, sa) in enumerate(timed):
        for b, sb in timed[i + 1:]:
            if sa[0] < sb[1] and sb[0] < sa[1]:
                found.append(Conflict(a, b, f"{a.title} и {b.title} пересекаются по времени"))
        for b_start, b_end, label in busy or []:
            if sa[0] < b_end and b_start < sa[1]:
                found.append(Conflict(a, a, f"«{a.title}» пересекается с занятостью: {label}"))
    return found
