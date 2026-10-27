"""End to end: WhatsApp export zip -> events -> digest."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import httpx

from . import asr, export_parser, extract, rules
from .config import Settings
from .events import Event

# Language hints that worked best in the Oct 27 check: Kazakh + Russian together.
PRIMARY_BIAS = ("Kazakh", "Russian")

# transcribe(path, language_bias) -> text
Transcriber = Callable[[Path, tuple[str, ...]], str]


@dataclass
class Result:
    events: list[Event] = field(default_factory=list)
    voice_total: int = 0
    unheard: int = 0              # voice notes that exist in the chat but not in the zip
    failed: list[str] = field(default_factory=list)
    transcripts: list[dict] = field(default_factory=list)  # for debugging and the demo


_KAZAKH_LETTERS = set("әғқңөұүһі")


def _extra_bias(text: str) -> tuple[str, ...]:
    """Third reading: a single-language hint, chosen by what the first reading looks like."""
    return ("Kazakh",) if _KAZAKH_LETTERS & set(text.lower()) else ("Russian",)


def default_transcriber(settings: Settings | None = None, client: httpx.Client | None = None) -> Transcriber:
    def run(path: Path, bias: tuple[str, ...]) -> str:
        return asr.transcribe_file(path, language_bias=bias, settings=settings, client=client).text
    return run


def process_export(
    zip_path: str | Path,
    *,
    since: datetime | None = None,
    transcribe: Transcriber | None = None,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
    cross_check: bool = True,
) -> Result:
    """since: only messages sent at or after this moment are read."""
    transcribe = transcribe or default_transcriber(settings)
    export = export_parser.load_export(zip_path)
    result = Result()

    with tempfile.TemporaryDirectory(prefix="qulaq_media_") as tmp:
        for msg in export.messages:
            if since and msg.ts < since:
                continue
            texts: list[tuple[str, str | None]] = []  # (text, attachment)
            if msg.text:
                texts.append((msg.text, None))

            if msg.is_voice:
                result.voice_total += 1
            if msg.media_omitted:
                result.unheard += 1

            if msg.is_voice:
                audio_path = export_parser.extract_attachment(export, msg, tmp)
                if audio_path is None:
                    result.unheard += 1
                else:
                    try:
                        main_text = transcribe(audio_path, PRIMARY_BIAS)
                        alt_text = transcribe(audio_path, ()) if cross_check else ""
                        third_text = (
                            transcribe(audio_path, _extra_bias(main_text)) if cross_check else ""
                        )
                    except Exception as exc:  # keep going when one voice note fails
                        result.failed.append(f"{msg.attachment}: {exc}")
                        continue
                    result.transcripts.append({"file": msg.attachment, "sent_at": msg.ts.isoformat(),
                                               "with_hint": main_text, "without_hint": alt_text,
                                               "third_pass": third_text})
                    main_ev = extract.extract_events(
                        main_text, sender=msg.sender, sent_at=msg.ts,
                        attachment=msg.attachment, client=client, settings=settings)
                    if cross_check:
                        for other in (alt_text, third_text):
                            if other:
                                other_ev = extract.extract_events(
                                    other, sender=msg.sender, sent_at=msg.ts,
                                    attachment=msg.attachment, client=client, settings=settings)
                                extract.cross_check(main_ev, other_ev)
                    main_ev = extract.money_safety_net(
                        [main_text, alt_text, third_text], main_ev,
                        sender=msg.sender, sent_at=msg.ts, attachment=msg.attachment)
                    result.events += main_ev

            for text, att in texts:
                result.events += extract.extract_events(
                    text, sender=msg.sender, sent_at=msg.ts, attachment=att,
                    client=client, settings=settings)

    result.events = rules.dedupe(rules.apply(result.events))
    return result
