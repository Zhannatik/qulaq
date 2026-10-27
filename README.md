# Qulaq («құлақ» — ear)

An agent for parents in Kazakhstan whose school and kindergarten live in WhatsApp groups.
It listens to the voice notes you missed, pulls out dates, deadlines, money and things to bring,
and gives you a short "don't miss this" report in the evening or once a week.

Status: work in progress for the Meta Global AI Developer Hackathon (Indie Developer track).

## Two ways in (no unofficial WhatsApp access)

1. **Export chat** — in WhatsApp: group → ⋮ → More → Export chat → *Include media*. Upload the `.zip`.
   WhatsApp keeps only the latest ~10,000 messages with media; older media is marked `<Media omitted>`,
   and Qulaq reports what it could not hear instead of guessing.
2. **Forward** — forward voice notes and messages to the Qulaq number (WhatsApp Business Cloud API). *Planned.*

Qulaq does not read groups by scraping or by unofficial libraries.

## Pipeline

export / forward → ffmpeg (mono 16-bit WAV) → Muse Voice Transcribe → Muse Spark extracts events
→ code rules decide what is important (date, payment, bring item, RSVP) → digest.

The model extracts fields and writes text; importance is decided by plain code rules.

**Never a confident wrong number.** Speech recognition can mishear "бес жүз" (500) as "үш жүз" (300).
Every voice note is read three ways (language hints Kazakh+Russian, none, and one single-language hint).
If amount, date or time differ, the item is marked ⚠️ with all variants and the original words.
A payment with no readable amount is never dropped: plain code adds a flagged item with the quote.

## Agent actions (MCP)

`python -m qulaq.mcp_server` exposes tools to any MCP client (Claude Desktop, etc.):
`read_chat_export`, `list_events`, `explain_doubts`, `export_calendar` (.ics with a reminder at 18:00 the
day before), `check_conflicts`. Doubtful events are not exported until the parent confirms them.

Claude Desktop config (`claude_desktop_config.json`):

```json
{"mcpServers": {"qulaq": {"command": "python", "args": ["-m", "qulaq.mcp_server"],
  "cwd": "C:\\path\\to\\qulaq"}}}
```

## Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # add MODEL_API_KEY
pytest
python scripts/check_asr.py voice.opus --dry-run     # test ffmpeg only
python scripts/check_asr.py ru.opus kk.opus mix.opus # real speech check
```

Needs `ffmpeg` on PATH. See `scripts/sample_texts.md` for the speech check.

## Privacy

Real chats involve children and teachers. Nothing real is committed (`.gitignore`); the demo uses
invented chats only.

## Related work

Other WhatsApp chat summarizers exist (text-focused GitHub summarizers, ChatBrief, ThreadRecap,
Kaption, WhatsApp's own message summaries, Amar Khobor). Qulaq differs by focusing on voice notes in
Kazakh/Russian school groups and on deadlines and actions rather than a generic summary.

## Provenance

All code in this repository was written during the hackathon period (Oct 27 – Nov 4, 2026). The idea
grew out of an earlier project (School Bridge); no code from it is reused.

## License

MIT
