import zipfile
from datetime import datetime

import pytest

from qulaq.export_parser import extract_attachment, load_export, parse_chat_text

ANDROID_US = """12/31/2026, 9:05 PM - Messages and calls are end-to-end encrypted.
12/31/2026, 9:05 PM - Aigerim: Concert on Friday
bring a white shirt
1/2/2027, 8:00 AM - Teacher: PTT-20261231-WA0001.opus (file attached)
"""

ANDROID_RU = """30.10.2026, 18:40 - Учитель: Собрание завтра в 18:00
30.10.2026, 18:41 - Учитель: AUD-20261030-WA0002.opus (файл добавлен)
30.10.2026, 18:42 - Мама: <Медиафайлы не включены>
30.10.2026, 18:43 - Учитель изменил(а) тему группы на «3А: Родители»
"""

IOS = "‎[05.11.2026, 14:03:22] Teacher: ‎<attached: 00000012-AUDIO-2026-11-05.opus>\n"


def test_us_month_first_detected_and_multiline():
    msgs = parse_chat_text(ANDROID_US, ["PTT-20261231-WA0001.opus"])
    assert len(msgs) == 2
    assert msgs[0].ts == datetime(2026, 12, 31, 21, 5)
    assert msgs[0].text == "Concert on Friday\nbring a white shirt"
    assert msgs[1].ts == datetime(2027, 1, 2, 8, 0)
    assert msgs[1].is_voice and msgs[1].text == ""


def test_day_first_ru_media_omitted_and_system_dropped():
    msgs = parse_chat_text(ANDROID_RU, ["AUD-20261030-WA0002.opus"])
    assert [m.sender for m in msgs] == ["Учитель", "Учитель", "Мама"]
    assert msgs[0].ts == datetime(2026, 10, 30, 18, 40)
    assert msgs[1].is_voice
    assert msgs[2].media_omitted and not msgs[2].is_voice


def test_ios_brackets_with_invisible_marks():
    msgs = parse_chat_text(IOS, ["00000012-AUDIO-2026-11-05.opus"])
    assert len(msgs) == 1
    assert msgs[0].ts == datetime(2026, 11, 5, 14, 3, 22)
    assert msgs[0].is_voice


def test_ambiguous_date_defaults_to_day_first():
    msgs = parse_chat_text("03.04.2026, 10:00 - A: hi\n")
    assert msgs[0].ts.month == 4 and msgs[0].ts.day == 3


def _make_zip(path, files):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)


def test_load_and_extract(tmp_path):
    z = tmp_path / "chat.zip"
    _make_zip(z, {"_chat.txt": ANDROID_RU, "AUD-20261030-WA0002.opus": b"x"})
    export = load_export(z)
    assert len(export.voice_messages) == 1
    out = extract_attachment(export, export.voice_messages[0], tmp_path / "out")
    assert out.read_bytes() == b"x" and out.parent == tmp_path / "out"


def test_zip_slip_member_ignored(tmp_path):
    z = tmp_path / "evil.zip"
    _make_zip(z, {"_chat.txt": "30.10.2026, 18:41 - A: ../evil.opus (file attached)\n",
                  "../evil.opus": b"x"})
    export = load_export(z)
    assert "evil.opus" not in export.members
    assert extract_attachment(export, export.messages[0], tmp_path / "out") is None
    assert not (tmp_path.parent / "evil.opus").exists()


def test_no_txt_raises(tmp_path):
    z = tmp_path / "empty.zip"
    _make_zip(z, {"a.opus": b"x"})
    with pytest.raises(ValueError):
        load_export(z)
