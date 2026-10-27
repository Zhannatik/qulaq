"""Make a digest from a WhatsApp export zip.

    python scripts/run_digest.py "C:\\path\\to\\WhatsApp Chat.zip" --days 7
    python scripts/run_digest.py chat.zip --days 7 --out digest.md --no-cross-check
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qulaq import digest, pipeline  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zip", type=Path, help="WhatsApp 'Export chat' .zip (with media)")
    ap.add_argument("--days", type=int, default=7, help="how many days back to read (default 7)")
    ap.add_argument("--now", help="pretend today is YYYY-MM-DD (for demos)")
    ap.add_argument("--out", type=Path, help="write the digest to this .md file")
    ap.add_argument("--save-transcripts", type=Path, help="write all voice transcripts to this .json file")
    ap.add_argument("--no-cross-check", action="store_true", help="transcribe each voice note once")
    args = ap.parse_args()

    now = datetime.fromisoformat(args.now) if args.now else datetime.now()
    result = pipeline.process_export(
        args.zip, since=now - timedelta(days=args.days), cross_check=not args.no_cross_check
    )
    text = digest.build_digest(result.events, now.date(), unheard=result.unheard)
    if args.save_transcripts:
        import json
        args.save_transcripts.write_text(
            json.dumps(result.transcripts, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"transcripts: {args.save_transcripts}")
    for problem in result.failed:
        print(f"skipped: {problem}", file=sys.stderr)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"written: {args.out}")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
