import json
import zipfile
from datetime import date, datetime

import httpx

from qulaq import digest, extract, llm, pipeline, rules
from qulaq.config import Settings
from qulaq.events import Event

S = Settings(api_key="k", api_base="https://api.test/v1", asr_model="m", llm_model="l")

CHAT = """27.10.2026, 15:38 - Teacher: PTT-1.opus (файл добавлен)
27.10.2026, 15:40 - Teacher: Завтра в 15:00 концерт, нужна белая рубашка
27.10.2026, 15:41 - Teacher: <Медиафайлы не включены>
"""


def _llm_client(replies):
    """Mock chat endpoint: picks the reply by what the user message contains."""
    def handler(req):
        user = json.loads(req.content)["messages"][-1]["content"]
        for needle, items in replies.items():
            if needle in user:
                body = json.dumps({"items": items}, ensure_ascii=False)
                return httpx.Response(200, json={"choices": [{"message": {"content": "```json\n" + body + "\n```"}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"items": []}'}}]})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parse_json_object_tolerates_chatter():
    assert llm.parse_json_object('Sure! {"a": {"b": "}"}} bye') == {"a": {"b": "}"}}


def test_parse_items_validates_fields():
    sent = datetime(2026, 10, 27, 15, 0)
    items = {"items": [
        {"kind": "payment", "title": "Шторы", "amount_kzt": "500 тг", "date": "not-a-date", "time": "25:99"},
        {"kind": "weird", "title": "Что-то", "date": "2026-10-01"},
        {"kind": "info", "title": ""},
    ]}
    evs = extract.parse_items(items, sender="T", sent_at=sent, attachment=None)
    assert len(evs) == 2
    assert evs[0].amount_kzt == 500 and evs[0].date is None and evs[0].time is None
    assert evs[1].kind == "info" and evs[1].uncertain  # date before the message was sent


def test_cross_check_flags_different_amounts():
    a = [Event(kind="payment", title="x", amount_kzt=500)]
    b = [Event(kind="payment", title="x", amount_kzt=300)]
    extract.cross_check(a, b)
    assert a[0].uncertain and "300" in a[0].notes[0] and "500" in a[0].notes[0]


def test_cross_check_same_values_not_flagged():
    a = [Event(kind="payment", title="x", amount_kzt=500)]
    extract.cross_check(a, [Event(kind="payment", title="x", amount_kzt=500)])
    assert not a[0].uncertain


def test_rules_levels_and_dedupe():
    evs = rules.apply([
        Event(kind="payment", title="Шторы", amount_kzt=500),
        Event(kind="info", title="Привет"),
        Event(kind="info", title="Привет"),
    ])
    assert evs[0].level == "must" and evs[1].level == "fyi"
    assert len(rules.dedupe(evs)) == 2


def test_digest_urgent_and_uncertain():
    today = date(2026, 10, 27)
    evs = rules.apply([
        Event(kind="event", title="Концерт", date=date(2026, 10, 28), time="15:00", sender="Учитель"),
        Event(kind="payment", title="Шторы", amount_kzt=500, uncertain=True, notes=["сумма: 500 или 300"]),
    ])
    text = digest.build_digest(evs, today, unheard=2)
    assert "Срочно" in text and "завтра" in text and "Концерт" in text
    assert "500 тг" in text and "Проверьте по оригиналу" in text and "2 голосовых" in text


def test_pipeline_end_to_end(tmp_path):
    z = tmp_path / "c.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("_chat.txt", CHAT)
        zf.writestr("PTT-1.opus", b"x")

    spoken = {(): "собрать по пятьсот тенге", ("Kazakh", "Russian"): "собрать по триста тенге",
              ("Russian",): "собрать по пятьсот тенге"}

    def transcribe(path, bias):
        return spoken[tuple(bias)]

    client = _llm_client({
        "пятьсот": [{"kind": "payment", "title": "Шторы", "amount_kzt": 500}],
        "триста": [{"kind": "payment", "title": "Шторы", "amount_kzt": 300}],
        "концерт": [{"kind": "event", "title": "Концерт", "date": "2026-10-28", "time": "15:00"},
                    {"kind": "bring", "title": "Белая рубашка", "date": "2026-10-28"}],
    })
    res = pipeline.process_export(z, transcribe=transcribe, settings=S, client=client)
    assert res.voice_total == 1 and res.unheard == 1
    pay = next(e for e in res.events if e.kind == "payment")
    assert pay.amount_kzt == 300 and pay.uncertain  # primary reading, flagged because the two differ
    assert {e.kind for e in res.events} == {"payment", "event", "bring"}
    assert "Концерт" in digest.build_digest(res.events, date(2026, 10, 27), unheard=res.unheard)


def test_merge_same_day_event_from_several_messages():
    d = date(2026, 10, 28)
    t1 = datetime(2026, 10, 27, 15, 38)
    t2 = datetime(2026, 10, 27, 15, 45)
    a = Event(kind="event", title="Мероприятие в школе", date=d, sent_at=t1, sender="Т",
              sources=[("Т", t1, "a.opus")])
    b = Event(kind="event", title="Праздничный концерт", date=d, time="15:00", sent_at=t2, sender="Т",
              sources=[("Т", t2, None)])
    out = rules.dedupe(rules.apply([a, b]))
    assert len(out) == 1
    m = out[0]
    assert m.title == "Праздничный концерт" and m.time == "15:00" and len(m.sources) == 2
    assert not m.uncertain and any("упомянуто" in n for n in m.notes)


def test_doubted_date_is_never_merged_away():
    """Regression: a voice note whose date was read two ways stays flagged on its own line."""
    d = date(2026, 10, 28)
    t1 = datetime(2026, 10, 27, 15, 38)
    t2 = datetime(2026, 10, 27, 15, 45)
    doubtful = Event(kind="event", title="Концерт", date=d, sent_at=t1, sources=[("Т", t1, "kk.opus")],
                     uncertain=True, notes=["дата: в двух расшифровках разные значения (a или b)"])
    other = Event(kind="event", title="Концерт", date=d, time="15:00", sent_at=t2, sources=[("Т", t2, None)])
    out = rules.dedupe(rules.apply([doubtful, other]))
    assert len(out) == 2
    assert [e for e in out if e.uncertain and e.sources[0][2] == "kk.opus"]


def test_payments_with_same_amount_stay_separate():
    evs = rules.apply([
        Event(kind="payment", title="Шторы", amount_kzt=500, date=date(2026, 10, 27)),
        Event(kind="payment", title="Стенгазета", amount_kzt=500),
    ])
    assert len(rules.dedupe(evs)) == 2


def test_amount_disagreement_shows_both_values():
    a = [Event(kind="payment", title="Стенгазета", amount_kzt=5)]
    b = [Event(kind="payment", title="Стенгазета", amount_kzt=500)]
    extract.cross_check(a, b)
    assert a[0].amount_options == [500, 5]
    text = digest.build_digest(rules.apply(a), date(2026, 10, 27))
    assert "сумма неясна: 500 или 5 тг" in text


def test_tiny_amount_is_flagged():
    evs = extract.parse_items({"items": [{"kind": "payment", "title": "x", "amount_kzt": 5}]},
                              sender="T", sent_at=datetime(2026, 10, 27), attachment=None)
    assert evs[0].uncertain


def test_missing_amount_in_one_reading_is_flagged():
    a = [Event(kind="payment", title="Пицца")]
    b = [Event(kind="payment", title="Пицца", amount_kzt=1000)]
    extract.cross_check(a, b)
    assert a[0].uncertain and a[0].amount_options == [1000]


def test_doubtful_past_item_is_not_hidden():
    ev = Event(kind="event", title="Концерт", date=date(2026, 10, 25), uncertain=True,
               notes=["дата раньше, чем сообщение отправлено; проверьте"])
    text = digest.build_digest(rules.apply([ev]), date(2026, 10, 27))
    assert "Проверьте: дата в прошлом" in text and "Концерт" in text


def test_payment_without_amount_is_flagged():
    evs = extract.parse_items({"items": [{"kind": "payment", "title": "Пицца"}]},
                              sender="T", sent_at=datetime(2026, 10, 27), attachment=None)
    assert evs[0].uncertain and "сумма не названа" in evs[0].notes[0]


def test_money_safety_net_adds_flagged_item_when_model_missed_payment():
    t = datetime(2026, 10, 27, 15, 39)
    text = "Сегодня был урок. За пиццу надо скинуть тысяч тенге маме Венеры. Сау болыңыздар."
    out = extract.money_safety_net([text, ""], [], sender="Т", sent_at=t, attachment="p.opus")
    assert len(out) == 1 and out[0].uncertain and "тенге" in out[0].quote
    md = digest.build_digest(rules.apply(out), date(2026, 10, 27))
    assert "Из записи: «За пиццу" in md and "Проверьте по оригиналу" in md


def test_money_safety_net_silent_when_payment_found_or_no_money():
    t = datetime(2026, 10, 27)
    pay = [Event(kind="payment", title="x", amount_kzt=500)]
    assert extract.money_safety_net(["сдать 500 тенге"], pay, sender="Т", sent_at=t, attachment=None) == pay
    assert extract.money_safety_net(["завтра концерт"], [], sender="Т", sent_at=t, attachment=None) == []


def test_third_pass_catches_error_shared_by_first_two():
    a = [Event(kind="payment", title="Стенгазета", amount_kzt=300, quote="үш жүз теңгеден", sources=[("Т", None, "k.opus")])]
    extract.cross_check(a, [Event(kind="payment", title="Стенгазета", amount_kzt=300)])
    assert not a[0].uncertain
    extract.cross_check(a, [Event(kind="payment", title="Стенгазета", amount_kzt=500)])
    assert a[0].uncertain and a[0].amount_options == [500, 300]


def test_voice_payment_always_shows_quote():
    ev = Event(kind="payment", title="Стенгазета", amount_kzt=300, quote="үш жүз теңгеден",
               sources=[("Т", datetime(2026, 10, 27, 15, 38), "k.opus")])
    md = digest.build_digest(rules.apply([ev]), date(2026, 10, 27))
    assert "Из записи: «үш жүз теңгеден»" in md


def test_extra_bias_depends_on_language():
    assert pipeline._extra_bias("ертең концерт") == ("Kazakh",)
    assert pipeline._extra_bias("завтра концерт") == ("Russian",)
