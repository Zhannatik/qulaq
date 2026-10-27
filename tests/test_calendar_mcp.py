import asyncio
import json
from datetime import date, datetime

from qulaq import calendar_ics, conflicts, mcp_server
from qulaq.events import Event

T = datetime(2026, 10, 27, 15, 45)


def _ev(**kw):
    base = dict(kind="event", title="Праздничный концерт", date=date(2026, 10, 28), time="15:00",
                sent_at=T, sources=[("Учитель", T, None)])
    base.update(kw)
    return Event(**base)


def _unfold(text):
    return text.replace("\r\n ", "").split("\r\n")


def test_ics_timed_event_with_reminder_and_crlf():
    text, exported, skipped = calendar_ics.events_to_ics([_ev()], now=T)
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    lines = _unfold(text)
    assert "DTSTART:20261028T150000" in lines and "DTEND:20261028T160000" in lines
    # reminder: 18:00 Almaty the day before = 13:00 UTC on 27 Oct
    assert "TRIGGER;VALUE=DATE-TIME:20261027T130000Z" in lines
    assert len(exported) == 1 and not skipped


def test_ics_all_day_event_and_escaping_and_folding():
    ev = _ev(time=None, title="Сбор, шторы; 500", kind="payment", amount_kzt=500,
             action="Сдать по 500 тенге на шторы в школу, учителю " * 3)
    text, _, _ = calendar_ics.events_to_ics([ev], now=T)
    assert all(len(line.encode("utf-8")) <= 75 for line in text.split("\r\n"))
    lines = _unfold(text)
    assert "DTSTART;VALUE=DATE:20261028" in lines and "DTEND;VALUE=DATE:20261029" in lines
    assert any(l.startswith("SUMMARY:Сдать деньги: Сбор\\, шторы\\; 500 (500 тг)") for l in lines)


def test_doubtful_and_undated_events_are_not_exported():
    events = [_ev(), _ev(title="Сомнительный", uncertain=True), _ev(title="Без даты", date=None)]
    _, exported, skipped = calendar_ics.events_to_ics(events, now=T)
    assert [e.title for e in exported] == ["Праздничный концерт"]
    assert {e.title for e in skipped} == {"Сомнительный", "Без даты"}
    _, with_doubtful, _ = calendar_ics.events_to_ics(events, include_uncertain=True, now=T)
    assert len(with_doubtful) == 2


def test_conflicts_between_events_and_with_busy_slot():
    a = _ev()
    b = _ev(title="Родительское собрание", time="15:30")
    c = _ev(title="Позже", time="17:00")
    found = conflicts.find_conflicts([a, b, c])
    assert len(found) == 1 and "пересекаются" in found[0].reason
    busy = [(datetime(2026, 10, 28, 16, 30), datetime(2026, 10, 28, 18, 0), "работа")]
    assert any("работа" in x.reason for x in conflicts.find_conflicts([c], busy=busy))
    assert conflicts.find_conflicts([_ev(time=None)]) == []


def test_mcp_tools_registered_and_work_on_loaded_events(tmp_path):
    names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert {"read_chat_export", "list_events", "export_calendar", "check_conflicts", "explain_doubts"} <= names

    good = _ev()
    doubtful = _ev(title="Стенгазета", kind="payment", time=None, uncertain=True, amount_options=[500, 5],
                   notes=["сумма: в двух расшифровках разные значения (5 или 500)"], quote="беш тенгеден",
                   sources=[("Учитель", T, "k.opus")])
    mcp_server.load_events([good, doubtful], today=date(2026, 10, 27))

    listed = json.loads(mcp_server.list_events(only_needing_check=True))
    assert len(listed) == 1 and listed[0]["needs_check"] and listed[0]["amount_options"] == [500, 5]
    assert "k.opus" in mcp_server.explain_doubts()

    out = json.loads(mcp_server.export_calendar(str(tmp_path / "x.ics")))
    assert out["exported"] == ["Праздничный концерт"]
    assert out["not_exported"][0]["title"] == "Стенгазета"
    assert (tmp_path / "x.ics").exists()
    assert "пересекаются" not in mcp_server.check_conflicts()
