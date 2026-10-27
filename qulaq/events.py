"""Data model for things a parent must know or do."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

KINDS = ("event", "deadline", "payment", "bring", "rsvp", "info")


@dataclass
class Event:
    kind: str
    title: str
    date: date | None = None
    time: str | None = None          # "HH:MM"
    amount_kzt: int | None = None
    action: str | None = None        # what the parent has to do
    quote: str = ""                  # the words it came from
    sender: str = ""
    sent_at: datetime | None = None
    attachment: str | None = None    # voice note file name, if any
    sources: list[tuple] = field(default_factory=list)  # (sender, sent_at, attachment)
    amount_options: list[int] = field(default_factory=list)  # set when two readings disagree
    uncertain: bool = False
    notes: list[str] = field(default_factory=list)
    score: int = 0                   # filled in by rules.py
    level: str = "fyi"               # must / should / fyi
