"""Parse a WhatsApp "Export chat" archive (.zip with _chat.txt and optional media).

Handles the Android and iOS layouts in any interface language. Attachments are
matched by the file names that are actually inside the zip, so the localized
wording of "(file attached)" or "<Media omitted>" does not matter.

Known WhatsApp limits (not ours): an export with media holds only the most recent
~10,000 messages, and older media shows up as "<Media omitted>". Such messages are
flagged with media_omitted=True so the digest can say what it could not hear.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Iterable

AUDIO_EXTS = {".opus", ".ogg", ".m4a", ".aac", ".mp3", ".amr", ".wav"}
_MEDIA_EXTS = AUDIO_EXTS | {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".3gp", ".pdf", ".docx", ".xlsx"}

MAX_CHAT_BYTES = 50 * 1024 * 1024
MAX_MEDIA_BYTES = 50 * 1024 * 1024

_INVISIBLE = dict.fromkeys(map(ord, "‎‏﻿‪‫‬‭‮"))

_HEADER = re.compile(
    r"^(?P<bracket>\[)?"
    r"(?P<d1>\d{1,2})[./-](?P<d2>\d{1,2})[./-](?P<y>\d{2,4}),?\s+"
    r"(?P<h>\d{1,2}):(?P<m>\d{2})(?::(?P<s>\d{2}))?"
    r"\s?(?P<ampm>[AaPp]\.?[Mm]\.?)?"
    r"(?(bracket)\]\s|\s[-–—]\s)"
    r"(?P<rest>.*)$"
)
_SENDER = re.compile(r"^(?P<sender>[^:\n]{1,60}?): (?P<body>.*)$", re.S)
_QUOTES = set('"“”„«»')
_FILE_FALLBACK = re.compile(
    r"[^\s<>()]+\.(?:" + "|".join(e.lstrip(".") for e in sorted(_MEDIA_EXTS)) + r")", re.I
)
_WRAPPED = re.compile(r"^[<(][^<>()]*[>)]$")


@dataclass
class Message:
    ts: datetime
    sender: str
    text: str = ""
    attachment: str | None = None
    media_omitted: bool = False

    @property
    def is_voice(self) -> bool:
        return bool(self.attachment) and Path(self.attachment).suffix.lower() in AUDIO_EXTS


@dataclass
class ChatExport:
    messages: list[Message]
    zip_path: Path | None = None
    members: dict[str, str] = field(default_factory=dict)  # basename -> member path in zip

    @property
    def voice_messages(self) -> list[Message]:
        return [m for m in self.messages if m.is_voice]


def _safe_member(name: str) -> bool:
    p = PurePosixPath(name.replace("\\", "/"))
    return not p.is_absolute() and ".." not in p.parts and bool(p.name)


def _detect_dayfirst(pairs: list[tuple[int, int]], default: bool) -> bool:
    if any(a > 12 for a, _ in pairs):
        return True
    if any(b > 12 for _, b in pairs):
        return False
    return default


def _find_attachment(body: str, names: list[str]) -> str | None:
    for name in names:  # longest first, so "a.opus" never shadows "xa.opus"
        if name in body:
            return name
    m = _FILE_FALLBACK.search(body)
    return m.group(0) if m else None


def _split_caption(body: str, attachment: str) -> str:
    first, _, rest = body.partition("\n")
    first = first.replace(attachment, "").strip()
    if _WRAPPED.match(first):
        first = ""
    return "\n".join(part for part in (first, rest.strip()) if part).strip()


def parse_chat_text(
    text: str,
    members: Iterable[str] = (),
    *,
    default_dayfirst: bool = True,
) -> list[Message]:
    """Parse the text of _chat.txt. members are the media file names present in the zip."""
    text = text.translate(_INVISIBLE).replace("\r\n", "\n").replace("\r", "\n")
    names = sorted(set(members), key=len, reverse=True)

    entries: list[dict] = []
    for line in text.split("\n"):
        m = _HEADER.match(line)
        if m:
            entries.append({"parts": m.groupdict(), "rest": m.group("rest")})
        elif entries:
            entries[-1]["rest"] += "\n" + line

    pairs = [(int(e["parts"]["d1"]), int(e["parts"]["d2"])) for e in entries]
    dayfirst = _detect_dayfirst(pairs, default_dayfirst)

    messages: list[Message] = []
    for e in entries:
        parts = e["parts"]
        sm = _SENDER.match(e["rest"].rstrip("\n"))
        if not sm or any(ch in _QUOTES for ch in sm.group("sender")):
            continue  # system line such as "Messages and calls are end-to-end encrypted"
        a, b = int(parts["d1"]), int(parts["d2"])
        day, month = (a, b) if dayfirst else (b, a)
        year = int(parts["y"])
        if year < 100:
            year += 2000
        hour, minute = int(parts["h"]), int(parts["m"])
        ampm = (parts["ampm"] or "").replace(".", "").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        try:
            ts = datetime(year, month, day, hour, minute, int(parts["s"] or 0))
        except ValueError:
            continue

        body = sm.group("body").strip()
        attachment = _find_attachment(body, names)
        omitted = False
        if attachment:
            body = _split_caption(body, attachment)
        elif _WRAPPED.match(body) and "<" in body:
            omitted = True  # e.g. "<Media omitted>" in any language
            body = ""
        messages.append(
            Message(ts=ts, sender=sm.group("sender").strip(), text=body,
                    attachment=attachment, media_omitted=omitted)
        )
    return messages


def load_export(zip_path: str | Path) -> ChatExport:
    zip_path = Path(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir() and _safe_member(i.filename)]
        txt = [i for i in infos if i.filename.lower().endswith(".txt")]
        if not txt:
            raise ValueError("No .txt chat file found inside the archive")
        chat = max(txt, key=lambda i: i.file_size)
        if chat.file_size > MAX_CHAT_BYTES:
            raise ValueError("Chat file is too large")
        raw = zf.read(chat).decode("utf-8-sig", errors="replace")
        members = {
            PurePosixPath(i.filename).name: i.filename
            for i in infos
            if i is not chat and i.file_size <= MAX_MEDIA_BYTES
        }
    return ChatExport(
        messages=parse_chat_text(raw, members.keys()), zip_path=zip_path, members=members
    )


def extract_attachment(export: ChatExport, message: Message, dest_dir: str | Path) -> Path | None:
    """Copy one attachment out of the zip. Only files listed in the archive are extracted,
    and they are always written under their plain file name inside dest_dir."""
    if not export.zip_path or not message.attachment:
        return None
    member = export.members.get(message.attachment)
    if member is None:
        return None
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / PurePosixPath(member).name
    with zipfile.ZipFile(export.zip_path) as zf, zf.open(member) as src, open(target, "wb") as out:
        out.write(src.read(MAX_MEDIA_BYTES + 1)[:MAX_MEDIA_BYTES])
    return target
