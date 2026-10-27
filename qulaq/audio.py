"""Convert WhatsApp voice notes (usually .opus) to what Muse Voice Transcribe accepts.

The file endpoint takes a RIFF/WAVE file with mono 16-bit PCM at 16 or 24 kHz, at most
10 minutes and 32 MB per request. Longer audio is split into chunks.
"""

from __future__ import annotations

import glob
import shutil
import subprocess
from pathlib import Path

MAX_CHUNK_SECONDS = 540  # stay under the 10 minute request limit
SAMPLE_RATE = 24000  # engine-native rate


class AudioError(RuntimeError):
    pass


def ensure_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise AudioError(
            "ffmpeg was not found on PATH. Install it (Windows: winget install Gyan.FFmpeg) "
            "and open a new terminal."
        )
    return path


def to_wav_chunks(
    src: Path,
    out_dir: Path,
    *,
    sample_rate: int = SAMPLE_RATE,
    chunk_seconds: int = MAX_CHUNK_SECONDS,
) -> list[Path]:
    """Convert any audio file to mono 16-bit PCM WAV chunks of at most chunk_seconds."""
    src = Path(src)
    if not src.is_file():
        raise AudioError(f"Audio file not found: {src}")
    ffmpeg = ensure_ffmpeg()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pattern = out_dir / f"{src.stem}_%03d.wav"
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(src),
        "-vn", "-ac", "1", "-ar", str(sample_rate), "-sample_fmt", "s16",
        "-f", "segment", "-segment_time", str(chunk_seconds), "-reset_timestamps", "1",
        str(pattern),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AudioError(proc.stderr.strip() or "ffmpeg failed")

    chunks = sorted(Path(p) for p in glob.glob(str(out_dir / (glob.escape(src.stem) + "_*.wav"))))
    if not chunks:
        raise AudioError(f"ffmpeg produced no output for {src.name}")
    return chunks
