"""Render the parent-facing report (Russian, plain Markdown)."""

from __future__ import annotations

from datetime import date

from .events import Event
from .rules import days_until

_KIND_ICON = {"event": "🎉", "deadline": "⏰", "payment": "💰", "bring": "🎒", "rsvp": "✋", "info": "ℹ️"}
_WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def _when(ev: Event, today: date) -> str:
    if not ev.date:
        return "без даты"
    d = days_until(ev, today)
    rel = {0: "сегодня", 1: "завтра"}.get(d, "")
    base = f"{ev.date:%d.%m} ({_WEEKDAYS[ev.date.weekday()]})"
    if rel:
        base = f"{rel}, {base}"
    return f"{base} {ev.time}" if ev.time else base


def _line(ev: Event, today: date) -> str:
    parts = [f"{_KIND_ICON.get(ev.kind, '•')} **{_when(ev, today)}** — {ev.title}"]
    if ev.amount_options:
        parts.append("сумма неясна: " + " или ".join(f"{a:,}".replace(",", " ") for a in ev.amount_options) + " тг")
    elif ev.amount_kzt and str(ev.amount_kzt) not in (ev.action or ""):
        parts.append(f"{ev.amount_kzt:,} тг".replace(",", " "))
    if ev.action:
        parts.append(ev.action)
    line = "- " + ". ".join(parts)
    srcs = ev.sources or [(ev.sender, ev.sent_at, ev.attachment)]
    src = "; ".join(
        f"{who}, {when:%d.%m %H:%M}" + (f", голосовое {att}" if att else "")
        if when else who
        for who, when, att in srcs
    )
    line += f"  \n  _{src}_"
    from_voice = any(att for _, _, att in (ev.sources or [(None, None, ev.attachment)]))
    if ev.quote and (ev.uncertain or (ev.kind == "payment" and from_voice)):
        line += f"  \n  Из записи: «{ev.quote}»"
    if ev.uncertain:
        line += "  \n  ⚠️ **Проверьте по оригиналу:** " + "; ".join(dict.fromkeys(ev.notes) or ["данные неточные"])
    elif ev.notes:
        line += "  \n  " + "; ".join(dict.fromkeys(ev.notes))
    return line


def build_digest(
    events: list[Event],
    today: date,
    *,
    title: str = "Qulaq: что нельзя пропустить",
    unheard: int = 0,
    horizon_days: int = 14,
) -> str:
    def sort_key(e: Event):
        return (e.date or date.max, e.time or "99:99")

    upcoming = [e for e in events if e.date is None or (days_until(e, today) or 0) >= 0]
    past_all = [e for e in events if e.date and (days_until(e, today) or 0) < 0]
    check_past = [e for e in past_all if e.uncertain]   # never hide a doubtful item
    past = [e for e in past_all if not e.uncertain]
    urgent = [e for e in upcoming if e.date and days_until(e, today) in (0, 1) and e.level != "fyi"]
    rest_must = [e for e in upcoming if e.level == "must" and e not in urgent
                 and (e.date is None or (days_until(e, today) or 0) <= horizon_days)]
    should = [e for e in upcoming if e.level == "should" and e not in urgent]

    out = [f"# {title}", f"_На {today:%d.%m.%Y}_", ""]
    if urgent:
        out += ["## Срочно: сегодня и завтра", *[_line(e, today) for e in sorted(urgent, key=sort_key)], ""]
    if rest_must:
        out += ["## Не пропустите", *[_line(e, today) for e in sorted(rest_must, key=sort_key)], ""]
    if should:
        out += ["## Хорошо бы знать", *[_line(e, today) for e in sorted(should, key=sort_key)], ""]
    if not (urgent or rest_must or should):
        out += ["Ничего важного в новых сообщениях не найдено.", ""]
    if check_past:
        out += ["## Проверьте: дата в прошлом или неясна",
                *[_line(e, today) for e in sorted(check_past, key=sort_key)], ""]
    unsure = [e for e in events if e.uncertain]
    if unsure:
        out += [f"_Пунктов с пометкой ⚠️: {len(unsure)}. Они распознаны неуверенно, "
                "сверьтесь с голосовым сообщением._", ""]
    if unheard:
        out += [f"_Не удалось прослушать {unheard} голосовых: в экспорте нет файла "
                "(WhatsApp не сохраняет старые медиа)._", ""]
    if past:
        out += [f"_Уже прошло: {len(past)}._", ""]
    return "\n".join(out).rstrip() + "\n"
