"""MCP server: lets an AI assistant read the digest and act on it.

Run:  python -m qulaq.mcp_server        (stdio, for Claude Desktop and other MCP clients)

Tools
  read_chat_export     read a WhatsApp export zip and keep the events in memory
  list_events          show them (optionally only the ones that need a check)
  export_calendar      write a .ics file with the confirmed events and reminders
  check_conflicts      find events that overlap, optionally against busy slots
  explain_doubts       what to verify in the original voice notes, and why
The assistant is told to ask the parent before exporting anything doubtful.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import calendar_ics, conflicts, digest, pipeline
from .events import Event

mcp = FastMCP("qulaq")

_STATE: dict = {"events": [], "unheard": 0, "today": None}


def _as_dict(ev: Event) -> dict:
    return {
        "kind": ev.kind,
        "title": ev.title,
        "date": ev.date.isoformat() if ev.date else None,
        "time": ev.time,
        "amount_kzt": ev.amount_kzt,
        "amount_options": ev.amount_options,
        "action": ev.action,
        "quote": ev.quote,
        "level": ev.level,
        "needs_check": ev.uncertain,
        "notes": list(dict.fromkeys(ev.notes)),
        "sources": [
            {"sender": who, "sent_at": when.isoformat() if when else None, "voice_file": att}
            for who, when, att in ev.sources
        ],
    }


def load_events(events: list[Event], *, today: date, unheard: int = 0) -> None:
    """Used by read_chat_export and by tests."""
    _STATE.update(events=events, today=today, unheard=unheard)


@mcp.tool()
def read_chat_export(zip_path: str, days: int = 7, today: str | None = None) -> str:
    """Read a WhatsApp 'Export chat' zip (with media), listen to voice notes, and return the
    parent digest in Russian. Keeps the events for the other tools. today is YYYY-MM-DD
    (default: the real date)."""
    now = datetime.fromisoformat(today) if today else datetime.now()
    result = pipeline.process_export(zip_path, since=now - timedelta(days=days))
    load_events(result.events, today=now.date(), unheard=result.unheard)
    return digest.build_digest(result.events, now.date(), unheard=result.unheard)


@mcp.tool()
def list_events(only_needing_check: bool = False) -> str:
    """List the events found, as JSON. needs_check=true means the voice note was understood
    unreliably (conflicting amount/date or missing details): verify it before acting."""
    events = [e for e in _STATE["events"] if e.uncertain or not only_needing_check]
    return json.dumps([_as_dict(e) for e in events], ensure_ascii=False, indent=2)


@mcp.tool()
def explain_doubts() -> str:
    """For every doubtful event: what is unclear and which voice message to listen to."""
    lines = []
    for e in _STATE["events"]:
        if not e.uncertain:
            continue
        files = ", ".join(att for _, _, att in e.sources if att) or "текстовое сообщение"
        lines.append(f"- {e.title}: {'; '.join(dict.fromkeys(e.notes))}. Послушайте: {files}."
                     + (f" Из записи: «{e.quote}»" if e.quote else ""))
    return "\n".join(lines) or "Сомнительных пунктов нет."


@mcp.tool()
def export_calendar(out_path: str = "qulaq_events.ics", include_doubtful: bool = False) -> str:
    """Write a .ics calendar file (opens in Google/Apple/Outlook) with a reminder at 18:00 the day
    before each event. By default doubtful events are NOT exported: ask the parent to confirm
    them first, then call again with include_doubtful=true only if they say so."""
    path, exported, skipped = calendar_ics.write_ics(
        _STATE["events"], out_path, include_uncertain=include_doubtful)
    return json.dumps(
        {
            "file": str(Path(path).resolve()),
            "exported": [e.title for e in exported],
            "not_exported": [
                {"title": e.title, "reason": "нет даты" if not e.date else "нужна проверка"}
                for e in skipped
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
def check_conflicts(busy: list[dict] | None = None) -> str:
    """Find events that overlap. busy is an optional list of
    {"start": "2026-10-28T14:30", "end": "2026-10-28T16:00", "label": "work meeting"}."""
    slots = [(datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"]), b.get("label", "занято"))
             for b in busy or []]
    found = conflicts.find_conflicts([e for e in _STATE["events"] if e.date and e.time], busy=slots)
    return "\n".join(f"- {c.reason}" for c in found) or "Конфликтов не найдено."


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
