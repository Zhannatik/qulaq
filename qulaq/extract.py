"""Turn one message (typed or transcribed) into structured events using the model.

The model only extracts fields. Whether something is important is decided later by
plain rules in rules.py, and every date it returns is checked by code.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import httpx

from . import llm
from .config import Settings
from .events import KINDS, Event

SYSTEM = """You read one message from a school or kindergarten parent group in Kazakhstan.
It is written or spoken in Russian, Kazakh, or a mix. Extract what a parent must know or do.

Return ONLY a JSON object: {"items": [ ... ]}. Each item:
  "kind": one of event | deadline | payment | bring | rsvp | info
  "title": short title in Russian
  "date": "YYYY-MM-DD" or null
  "time": "HH:MM" (24h) or null
  "amount_kzt": integer tenge per family/child, or null
  "action": what the parent has to do, in Russian, or null
  "quote": the exact words from the message this is based on

Rules:
- Use only what the message says. Never guess a date, time or amount. Use null if it is not stated.
- If the message gives an explicit calendar date (for example "25 қазан" or "25 октября"), use that date even when
  it also says "tomorrow" or similar. Never replace an explicit date with one computed from a relative word.
- Resolve words like "tomorrow", "Friday", "завтра", "ертең", "жұма" from the message date given below.
- "bring" is for things to bring or wear (white shirt, notebook). "payment" is for money to hand in.
- Kazakh months: қаңтар=1 ақпан=2 наурыз=3 сәуір=4 мамыр=5 маусым=6 шілде=7 тамыз=8
  қыркүйек=9 қазан=10 қараша=11 желтоқсан=12. Spoken numbers: "жиырма бесінші"=25th,
  "үш жүз"=300, "бес жүз"=500, "мың"=1000.
  "тысяча / тысячу / тысяч / тыща / тыщ / мың" with no multiplier means 1000. "полторы тысячи"=1500.
- If a word in the message is garbled or unclear, do not guess what it means: leave that detail out.
- A payment with no stated amount is still a payment item: use amount_kzt null.
- Greetings, thanks and chatter are not items. If nothing needs attention, return {"items": []}.
- One message can hold several items (a concert, a shirt to wear, and money to bring)."""

_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _clean_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _clean_amount(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    if isinstance(value, str):
        digits = re.sub(r"[^\d]", "", value)
        return int(digits) if digits else None
    return None


def _clean_time(value: object) -> str | None:
    if isinstance(value, str):
        m = _TIME.match(value.strip())
        if m:
            return f"{int(m.group(1)):02d}:{m.group(2)}"
    return None


def parse_items(payload: dict, *, sender: str, sent_at: datetime | None,
                attachment: str | None) -> list[Event]:
    events: list[Event] = []
    for raw in payload.get("items") or []:
        if not isinstance(raw, dict):
            continue
        kind = raw.get("kind") if raw.get("kind") in KINDS else "info"
        title = str(raw.get("title") or "").strip()
        if not title:
            continue
        ev = Event(
            kind=kind,
            title=title,
            date=_clean_date(raw.get("date")),
            time=_clean_time(raw.get("time")),
            amount_kzt=_clean_amount(raw.get("amount_kzt")),
            action=(str(raw["action"]).strip() or None) if raw.get("action") else None,
            quote=str(raw.get("quote") or "").strip(),
            sender=sender,
            sent_at=sent_at,
            attachment=attachment,
            sources=[(sender, sent_at, attachment)],
        )
        if ev.kind == "payment" and ev.amount_kzt is None:
            ev.uncertain = True
            ev.notes.append("сумма не названа или не расслышана; проверьте по оригиналу")
        if ev.amount_kzt is not None and ev.amount_kzt < 50:
            ev.uncertain = True
            ev.notes.append(f"сумма {ev.amount_kzt} тг подозрительно мала; проверьте")
        if ev.date and sent_at and ev.date < sent_at.date():
            ev.uncertain = True
            ev.notes.append("дата раньше, чем сообщение отправлено; проверьте")
        events.append(ev)
    return events


def extract_events(
    text: str,
    *,
    sender: str,
    sent_at: datetime,
    attachment: str | None = None,
    client: httpx.Client | None = None,
    settings: Settings | None = None,
) -> list[Event]:
    if not text.strip():
        return []
    weekday = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][sent_at.weekday()]
    user = f"Message date: {sent_at:%Y-%m-%d} ({weekday}), time {sent_at:%H:%M}\nSender: {sender}\n\nMessage:\n{text}"
    reply = llm.chat(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        client=client,
        settings=settings,
    )
    return parse_items(llm.parse_json_object(reply), sender=sender, sent_at=sent_at, attachment=attachment)


def cross_check(primary: list[Event], alt: list[Event]) -> None:
    """Compare two readings of the same voice note (different language hints).

    If amounts, dates or times disagree, mark the primary events as uncertain and
    show both values. The code does not decide which one is right.
    """
    def values(events: list[Event], attr: str) -> set:
        return {getattr(e, attr) for e in events if getattr(e, attr) is not None}

    labels = {"amount_kzt": "сумма", "date": "дата", "time": "время"}
    for attr, label in labels.items():
        a, b = values(primary, attr), values(alt, attr)
        if not a and b and attr == "amount_kzt":
            # a payment whose amount was heard in only one of the two readings
            for e in primary:
                if e.kind == "payment" and e.amount_kzt is None:
                    e.uncertain = True
                    e.amount_options = sorted(b, reverse=True)
                    e.notes.append(f"сумма: услышана только во второй расшифровке ({_fmt(b)})")
            continue
        if not a:
            continue
        if b and a != b:
            note = f"{label}: в двух расшифровках разные значения ({_fmt(a)} или {_fmt(b)})"
        elif not b and alt:
            note = f"{label}: во второй расшифровке не найдено"
        else:
            continue
        for e in primary:
            if getattr(e, attr) is not None:
                e.uncertain = True
                e.notes.append(note)
                if attr == "amount_kzt" and b:
                    e.amount_options = sorted(set(e.amount_options) | a | b, reverse=True)


def _fmt(values_: set) -> str:
    return ", ".join(sorted(str(x) for x in values_))


_MONEY = re.compile(r"тенге|теңге|тг\b|₸|скин|сдат|сдач|сбор|деньг|денег", re.I)


def money_safety_net(
    texts: list[str],
    events: list[Event],
    *,
    sender: str,
    sent_at: datetime,
    attachment: str | None,
) -> list[Event]:
    """If a transcript talks about money but the model returned no payment, say so.

    A silently lost request for money is worse than an unclear one, so this is done by
    plain code and does not depend on the model.
    """
    if any(e.kind == "payment" for e in events):
        return events
    for text in texts:
        if not text:
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            m = _MONEY.search(sentence)
            if m:
                if len(sentence) > 160:  # transcripts without punctuation come as one long line
                    sentence = "…" + sentence[max(0, m.start() - 80): m.end() + 80].strip() + "…"
                ev = Event(
                    kind="payment",
                    title="Упомянуты деньги, детали не разобраны",
                    action="Послушайте голосовое сообщение",
                    quote=sentence.strip(),
                    sender=sender,
                    sent_at=sent_at,
                    attachment=attachment,
                    sources=[(sender, sent_at, attachment)],
                    uncertain=True,
                    notes=["в записи есть слова про деньги, но сумму и срок не удалось определить"],
                )
                return events + [ev]
    return events
