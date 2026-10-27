"""Client for Muse Voice Transcribe (file endpoint).

POST {MODEL_API_BASE}/asr/transcribe with a multipart upload of one WAV file.
The server expects two multipart parts: "audio" (the WAV) and "request" (JSON with
model, mode, optional keywords / language bias). The names of the keys inside the
JSON are still guesses, isolated in the FIELD_* constants so they can be fixed in one place; compare with transcribe_file.py in the Meta cookbook
(06_muse_voice/01_voice_api_fundamentals) if the server answers with a 400.
"""

from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

import httpx

from . import audio
from .config import Settings, get_settings

FIELD_FILE = "audio"      # the server wants a multipart part named "audio" ...
FIELD_REQUEST = "request"  # ... and a JSON part named "request" (confirmed by its 400 message)
FIELD_MODE = "mode"
FIELD_MODEL = "model"
FIELD_LANGUAGE_BIAS = "languageBias"
FIELD_KEYWORDS = "keywords"
FIELD_ENCODING = "audioEncoding"  # required; documented value is "WAV"
DEFAULT_ENCODING = "WAV"  # per dev.meta.ai/docs/speech-to-text: mono 16-bit PCM WAV, 16 or 24 kHz

ENDPOINT = "/asr/transcribe"


class ASRError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass
class Transcript:
    text: str
    turns: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


def _parse_payload(payload: object, fallback_text: str = "") -> Transcript:
    if not isinstance(payload, dict):
        return Transcript(text=fallback_text.strip())
    turns = payload.get("turns") or []
    text = payload.get("transcript") or payload.get("text") or ""
    if not text and turns:
        text = " ".join(str(t.get("transcript", "")) for t in turns if isinstance(t, dict))
    return Transcript(text=str(text).strip(), turns=list(turns), raw=payload)


def transcribe_wav(
    path: Path,
    *,
    language_bias: Sequence[str] = (),
    keywords: Sequence[str] = (),
    mode: str = "PUSH_TO_TALK",
    client: httpx.Client | None = None,
    settings: Settings | None = None,
    extra_fields: dict[str, str] | None = None,
    retries: int = 2,
    backoff_s: float = 1.0,
) -> Transcript:
    """Transcribe one WAV file (mono 16-bit PCM, 16/24 kHz, up to 10 minutes)."""
    settings = settings or get_settings()
    if not settings.api_key:
        raise ASRError("MODEL_API_KEY is not set (see .env.example)")

    # Keys inside the JSON "request" part are still best guesses; the server's 400 body says if wrong.
    request: dict[str, object] = {
        FIELD_MODE: mode,
        FIELD_MODEL: settings.asr_model,
        FIELD_ENCODING: DEFAULT_ENCODING,
    }
    if language_bias:
        request[FIELD_LANGUAGE_BIAS] = list(language_bias)
    if keywords:
        request[FIELD_KEYWORDS] = list(keywords)
    if extra_fields:
        request.update(extra_fields)
    request_json = json.dumps(request, ensure_ascii=False)

    headers = {"Authorization": f"Bearer {settings.api_key}", "Accept": "application/json"}
    url = settings.api_base + ENDPOINT
    own_client = client is None
    client = client or httpx.Client(timeout=120)
    try:
        last: httpx.Response | None = None
        for attempt in range(retries + 1):
            with open(path, "rb") as fh:
                files = {
                    FIELD_REQUEST: (None, request_json, "application/json"),
                    FIELD_FILE: (Path(path).name, fh, "audio/wav"),
                }
                try:
                    last = client.post(url, headers=headers, files=files)
                except httpx.HTTPError as exc:
                    if attempt == retries:
                        raise ASRError(f"Network error: {exc}") from exc
                    time.sleep(backoff_s * (attempt + 1))
                    continue
            if last.status_code == 429 or last.status_code >= 500:
                if attempt < retries:
                    time.sleep(backoff_s * (attempt + 1))
                    continue
            break
        assert last is not None
        if last.status_code >= 400:
            raise ASRError(
                f"ASR request failed with HTTP {last.status_code}",
                status=last.status_code,
                body=last.text[:2000],
            )
        try:
            return _parse_payload(last.json(), fallback_text=last.text)
        except ValueError:
            return Transcript(text=last.text.strip())
    finally:
        if own_client:
            client.close()


def transcribe_file(
    path: Path,
    *,
    language_bias: Sequence[str] = (),
    keywords: Sequence[str] = (),
    mode: str = "PUSH_TO_TALK",
    client: httpx.Client | None = None,
    settings: Settings | None = None,
    extra_fields: dict[str, str] | None = None,
) -> Transcript:
    """Transcribe any audio file: convert with ffmpeg, split if long, join the text."""
    with tempfile.TemporaryDirectory(prefix="qulaq_") as tmp:
        chunks = audio.to_wav_chunks(Path(path), Path(tmp))
        parts: list[Transcript] = [
            transcribe_wav(
                c,
                language_bias=language_bias,
                keywords=keywords,
                mode=mode,
                client=client,
                settings=settings,
                extra_fields=extra_fields,
            )
            for c in chunks
        ]
    if len(parts) == 1:
        return parts[0]
    return Transcript(
        text=" ".join(p.text for p in parts if p.text),
        turns=[t for p in parts for t in p.turns],
        raw={"chunks": [p.raw for p in parts]},
    )


def iter_languages(values: Iterable[str]) -> list[str]:
    return [v.strip() for v in values if v and v.strip()]
