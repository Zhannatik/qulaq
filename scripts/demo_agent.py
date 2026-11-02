"""Show Qulaq as an MCP server: a small MCP client calls its tools, like an assistant would.

    python scripts/demo_agent.py "C:\\path\\WhatsApp Chat - Test.zip" --today 2026-11-01
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent


def say(title: str, text: str = "") -> None:
    print(f"\n=== {title}")
    if text:
        print(text)


def text_of(result) -> str:
    return "\n".join(c.text for c in result.content if getattr(c, "text", None))


async def run(zip_path: str, today: str | None, days: int, ics: str) -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "qulaq.mcp_server"], cwd=str(ROOT), env=dict(os.environ))
    async with stdio_client(params, errlog=open(os.devnull, "w")) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            say("Tools offered by the Qulaq MCP server", "\n".join(f"- {t.name}" for t in tools.tools))

            say("1. read_chat_export (listens to the voice notes, takes about a minute)")
            args = {"zip_path": zip_path, "days": days}
            if today:
                args["today"] = today
            await session.call_tool("read_chat_export", args)
            events = json.loads(text_of(await session.call_tool("list_events", {})))
            print(f"done: {len(events)} items found, {sum(1 for e in events if e['needs_check'])} need a check")

            say("2. check_conflicts", text_of(await session.call_tool("check_conflicts", {})))
            say("3. explain_doubts", text_of(await session.call_tool("explain_doubts", {})))
            say("4. export_calendar (doubtful items stay out)")
            out = json.loads(text_of(await session.call_tool("export_calendar", {"out_path": ics})))
            print("exported:", ", ".join(out["exported"]) or "nothing")
            for item in out["not_exported"]:
                print(f"not exported: {item['title']} ({item['reason']})")
            print("file:", out["file"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zip", help="WhatsApp export .zip (with media)")
    ap.add_argument("--today", help="pretend today is YYYY-MM-DD")
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--ics", default="qulaq_events.ics")
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(run(a.zip, a.today, a.days, a.ics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
