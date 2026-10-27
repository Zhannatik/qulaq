"""Go/no-go check: does Muse Voice Transcribe understand your voice notes?

Examples
    python scripts/check_asr.py ru.opus kk.opus mix.opus
    python scripts/check_asr.py kk.opus --expected kk.txt
    python scripts/check_asr.py kk.opus --lang Kazakh          # compare with and without a bias
    python scripts/check_asr.py kk.opus --dry-run              # only test the ffmpeg conversion

Record the voice notes in WhatsApp itself (sample texts: scripts/sample_texts.md), export
the chat with media, and unzip it. The .opus files can be passed in as they are.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qulaq import asr, audio  # noqa: E402
from qulaq.metrics import cer  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", type=Path, help="voice notes (.opus, .m4a, .wav, ...)")
    ap.add_argument("--expected", action="append", type=Path, default=[],
                    help="text file with what was said; repeat once per audio file, same order")
    ap.add_argument("--lang", action="append", default=[], help="language bias, e.g. Russian (repeatable)")
    ap.add_argument("--keywords", action="append", default=[], help="words to bias towards (repeatable)")
    ap.add_argument("--mode", default="PUSH_TO_TALK", choices=["PUSH_TO_TALK", "ENDPOINTING", "DIARIZATION"])
    ap.add_argument("--field", action="append", default=[], metavar="KEY=VALUE",
                    help="extra/override field in the JSON request part, e.g. --field audioEncoding=WAV")
    ap.add_argument("--dry-run", action="store_true", help="convert only, do not call the API")
    args = ap.parse_args()

    if args.expected and len(args.expected) != len(args.files):
        ap.error("--expected must be given once per audio file")

    extra = dict(f.split("=", 1) for f in args.field if "=" in f)
    failures = 0
    for idx, path in enumerate(args.files):
        print(f"\n=== {path.name}")
        try:
            if args.dry_run:
                with tempfile.TemporaryDirectory(prefix="qulaq_check_") as tmp:
                    chunks = audio.to_wav_chunks(path, Path(tmp))
                    print(f"ffmpeg OK: {len(chunks)} chunk(s), first is {chunks[0].stat().st_size} bytes")
                continue
            result = asr.transcribe_file(
                path, language_bias=args.lang, keywords=args.keywords, mode=args.mode,
                extra_fields=extra or None,
            )
        except audio.AudioError as exc:
            failures += 1
            print(f"AUDIO ERROR: {exc}")
            continue
        except asr.ASRError as exc:
            failures += 1
            print(f"ASR ERROR: {exc}")
            if exc.body:
                print(f"server said: {exc.body}")
            continue

        print(f"transcript: {result.text or '(empty)'}")
        if args.expected:
            expected = args.expected[idx].read_text(encoding="utf-8")
            print(f"CER vs expected: {cer(expected, result.text):.1%}  (lower is better; 0% = identical)")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
