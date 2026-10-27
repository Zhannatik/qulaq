"""Export confirmed events as an iCalendar (.ics) file.

Only events with a date and without doubts are exported by default. A wrong
calendar entry is worse than a missing one, so doubtful items are listed back to
the caller (and the parent) instead of being written silently.

Times are written as local ("floating") times, which is right for a school in one
time zone. Each event gets a reminder at 18:00 local time on the day before.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .events import Event

LOCAL_UTC_OFFSET = timedelta(hours=5)  # Kazakhstan (Almaty/Astana), no daylight saving
REMINDER_LOCAL_HOUR = 18
DEFAULT_DURATION = timedelta(hours=1)


def _esc(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _fold(line: str) -> list[str]:
    """RFC 5545: lines are at most 75 octets; continuation lines start with a space."""
    out: list[str] = []
    current = ""
    for ch in line:
        if len((current + ch).encode("utf-8")) > (75 if not out else 74):
            out.append(current)
            current = ch
        else:
            current += ch
    out.append(current)
    return [out[0]] + [" " + p for p in out[1:]]


def _uid(ev: Event) -> str:
    key = f"{ev.kind}|{ev.date}|{ev.time}|{ev.title.lower()}|{ev.amount_kzt}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:20] + "@qulaq"


def _summary(ev: Event) -> str:
    prefix = {"payment": "Сдать деньги: ", "bring": "Взять/надеть: ", "deadline": "Срок: "}.get(ev.kind, "")
    amount = f" ({ev.amount_kzt} тг)" if ev.amount_kzt else ""
    return f"{prefix}{ev.title}{amount}"


def exportable(ev: Event) -> bool:
    return ev.date is not None and not ev.uncertain


def _vevent(ev: Event, stamp: str) -> list[str]:
    assert ev.date is not None
    lines = ["BEGIN:VEVENT", f"UID:{_uid(ev)}", f"DTSTAMP:{stamp}", f"SUMMARY:{_esc(_summary(ev))}"]
    if ev.time:
        h, m = (int(x) for x in ev.time.split(":"))
        start = datetime(ev.date.year, ev.date.month, ev.date.day, h, m)
        lines += [f"DTSTART:{start:%Y%m%dT%H%M%S}", f"DTEND:{start + DEFAULT_DURATION:%Y%m%dT%H%M%S}"]
    else:
        lines += [f"DTSTART;VALUE=DATE:{ev.date:%Y%m%d}",
                  f"DTEND;VALUE=DATE:{ev.date + timedelta(days=1):%Y%m%d}"]
    desc = [d for d in (ev.action, "Источник: Qulaq, " + ", ".join(
        f"{who} {when:%d.%m %H:%M}" for who, when, _ in ev.sources if when) if ev.sources else None) if d]
    if desc:
        lines.append(f"DESCRIPTION:{_esc(' | '.join(desc))}")
    prev_day = datetime(ev.date.year, ev.date.month, ev.date.day) - timedelta(days=1)
    alarm_local = prev_day.replace(hour=REMINDER_LOCAL_HOUR)
    alarm_utc = (alarm_local - LOCAL_UTC_OFFSET).replace(tzinfo=timezone.utc)
    lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(_summary(ev))}",
              f"TRIGGER;VALUE=DATE-TIME:{alarm_utc:%Y%m%dT%H%M%SZ}", "END:VALARM", "END:VEVENT"]
    return lines


def events_to_ics(events: list[Event], *, include_uncertain: bool = False,
                  now: datetime | None = None) -> tuple[str, list[Event], list[Event]]:
    """Returns (ics_text, exported, skipped). Skipped = no date, or doubtful."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    exported = [e for e in events if e.date and (include_uncertain or not e.uncertain)]
    skipped = [e for e in events if e not in exported]
    body = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Qulaq//school parent digest//RU", "CALSCALE:GREGORIAN"]
    for ev in exported:
        body += _vevent(ev, stamp)
    body.append("END:VCALENDAR")
    folded = [piece for line in body for piece in _fold(line)]
    return "\r\n".join(folded) + "\r\n", exported, skipped


def write_ics(events: list[Event], path: str | Path, **kw) -> tuple[Path, list[Event], list[Event]]:
    text, exported, skipped = events_to_ics(events, **kw)
    path = Path(path)
    if path.suffix.lower() != ".ics":
        path = path.with_suffix(".ics")
    path.write_text(text, encoding="utf-8", newline="")
    return path, exported, skipped

