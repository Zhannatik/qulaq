"""Plain-code rules for what deserves a parent's attention. No model involved."""

from __future__ import annotations

from datetime import date, datetime

from .events import Event


def score(ev: Event) -> int:
    s = 0
    if ev.amount_kzt or ev.kind == "payment":
        s += 3
    if ev.kind == "deadline":
        s += 3
    if ev.kind in ("event", "rsvp"):
        s += 2
    if ev.kind == "bring":
        s += 2
    if ev.date:
        s += 2
    if ev.action:
        s += 1
    return s


def level(s: int) -> str:
    if s >= 3:
        return "must"
    if s >= 1:
        return "should"
    return "fyi"


def apply(events: list[Event]) -> list[Event]:
    for ev in events:
        ev.score = score(ev)
        ev.level = level(ev.score)
    return events


def days_until(ev: Event, today: date) -> int | None:
    return (ev.date - today).days if ev.date else None


def _date_doubt(ev: Event) -> bool:
    return any(n.startswith("дата:") for n in ev.notes)


def _key(ev: Event) -> tuple:
    if ev.kind in ("event", "bring", "rsvp") and ev.date:
        # one concert / one dress code per day. An item whose date was read two different
        # ways is never merged into others: another message cannot confirm its date.
        return (ev.kind, ev.date, _date_doubt(ev))
    return (ev.kind, ev.date, ev.amount_kzt, ev.title.lower())


def _pick_title(group: list[Event]) -> Event:
    """The entry to keep as the base: prefer one with a time, then the most detailed text."""
    return max(group, key=lambda e: (e.time is not None, len(e.action or "") + len(e.title)))


def _merge(group: list[Event]) -> Event:
    base = _pick_title(group)
    merged = Event(**{**base.__dict__, "notes": list(base.notes), "sources": []})
    for e in sorted(group, key=lambda e: e.sent_at or datetime.min):
        for src in e.sources:
            if src not in merged.sources:
                merged.sources.append(src)
        merged.time = merged.time or e.time
        merged.amount_kzt = merged.amount_kzt or e.amount_kzt
        merged.action = merged.action or e.action
        merged.amount_options = sorted(set(merged.amount_options) | set(e.amount_options), reverse=True)
        for n in e.notes:
            if n not in merged.notes:
                merged.notes.append(n)
    merged.uncertain = any(e.uncertain for e in group)
    messages = {(s_[1], s_[2]) for s_ in merged.sources}
    if len(messages) > 1:
        merged.notes.append(f"упомянуто в сообщениях: {len(messages)}")
    return merged


def dedupe(events: list[Event]) -> list[Event]:
    """Merge repeats of the same thing (a teacher posts it, then reminds in a voice note)."""
    groups: dict[tuple, list[Event]] = {}
    for ev in sorted(events, key=lambda e: e.sent_at or datetime.min):
        groups.setdefault(_key(ev), []).append(ev)
    return [g[0] if len(g) == 1 else _merge(g) for g in groups.values()]
