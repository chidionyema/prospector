#!/usr/bin/env python3
"""Read back everything the founder has ever said, in one command.

Pairs with `directive-capture.py`, the UserPromptSubmit hook that appends each message as it is
sent. This side does two jobs:

  --backfill   mine the existing transcript .jsonl files into the same log, once, so the record
               starts at the beginning of the project and not at the day the hook was installed.
  (default)    search and print, newest last, so an agent can answer "what did he say about X"
               without writing a bespoke scanner for the fifth time.

Examples:
    python3 ~/.claude/scripts/directives.py --backfill
    python3 ~/.claude/scripts/directives.py --grep 'laptop|emergenc' --limit 40
    python3 ~/.claude/scripts/directives.py --since 2026-08-18 --full
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HOME = Path.home()
LOG_DIR = HOME / ".claude" / "directives"
PROJECTS = HOME / ".claude" / "projects"

# Harness-injected text that arrives shaped like a user turn but is not the founder speaking.
NOISE = re.compile(
    r"^(<command-name>|<local-command|<system-reminder>|Caveat: The messages below|"
    r"\[Request interrupted|<user-prompt-submit-hook>|This session is being continued)",
)


def slug_for(cwd: str) -> str:
    return cwd.replace("/", "-") or "-unknown"


def log_path(cwd: str) -> Path:
    return LOG_DIR / f"{slug_for(cwd)}.jsonl"


def _text_of(msg: dict) -> str:
    """A user message's content is either a string or a list of blocks."""
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(p for p in parts if p)
    return ""


def backfill(cwd: str) -> int:
    """Mine transcripts for user turns and merge them into the log. Idempotent: dedupes on text."""
    proj = PROJECTS / slug_for(cwd)
    if not proj.is_dir():
        print(f"no transcript directory at {proj}", file=sys.stderr)
        return 1
    path = log_path(cwd)
    seen: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                seen.add(json.loads(line)["prompt"][:200])
            except Exception:
                continue
    rows: list[dict] = []
    for tr in sorted(proj.glob("*.jsonl")):
        try:
            fh = tr.open(encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"user"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                msg = rec.get("message") or {}
                if msg.get("role") != "user" or rec.get("isMeta"):
                    continue
                text = _text_of(msg).strip()
                if not text or text.startswith("/") or NOISE.match(text):
                    continue
                key = text[:200]
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "ts": rec.get("timestamp", ""),
                    "session": rec.get("sessionId", ""),
                    "cwd": cwd,
                    "prompt": text,
                })
    rows.sort(key=lambda r: r["ts"])
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"backfilled {len(rows)} message(s) into {path}")
    return 0


def read(cwd: str, pattern: str | None, since: str | None, limit: int, full: bool) -> int:
    path = log_path(cwd)
    if not path.exists():
        print(f"no log at {path} — run with --backfill first", file=sys.stderr)
        return 1
    rx = re.compile(pattern, re.I) if pattern else None
    hits = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        if since and row.get("ts", "") < since:
            continue
        if rx and not rx.search(row.get("prompt", "")):
            continue
        hits.append(row)
    hits.sort(key=lambda r: r.get("ts", ""))
    for row in hits[-limit:]:
        text = row["prompt"] if full else row["prompt"][:600]
        print(f"\n--- {row.get('ts', '?')}")
        print(text)
    print(f"\n{len(hits)} match(es); showing the last {min(limit, len(hits))}.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Search everything the founder has said in a project.")
    ap.add_argument("--cwd", default=str(HOME / "Documents" / "code" / "prospector"),
                    help="project root whose log to read (default: prospector)")
    ap.add_argument("--backfill", action="store_true", help="mine transcripts into the log, then exit")
    ap.add_argument("--grep", help="regex, case-insensitive")
    ap.add_argument("--since", help="ISO date, e.g. 2026-08-18")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--full", action="store_true", help="print whole messages, not the first 600 chars")
    args = ap.parse_args()
    if args.backfill:
        return backfill(args.cwd)
    return read(args.cwd, args.grep, args.since, args.limit, args.full)


if __name__ == "__main__":
    sys.exit(main())
