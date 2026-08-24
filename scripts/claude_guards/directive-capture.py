#!/usr/bin/env python3
"""Capture every founder message to a durable, queryable log, in every project, forever.

The class of failure this closes: the founder said a thing once, a session compacted, and the next
agent asked him to say it again. On 2026-08-19 he wrote: "you have lost dontet and not taking
notes ... i have to be renebering stuuf five said ... anythingn i talk regading this progran ghas
ben docunennted". The record DID exist -- spread over ~4000 transcript .jsonl files -- but
retrieving it needed a bespoke script each time, so in practice it did not exist.

Transcripts are the raw material. This is the index. One append per prompt, with no judgment about
what matters, because what matters is only knowable later.

UserPromptSubmit hook. It never blocks and never fails a turn: any error exits 0 silently.
Read it back with:  python3 ~/.claude/scripts/directives.py --grep migration
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path.home() / ".claude" / "directives"


def slug(cwd: str) -> str:
    """Match Claude Code's own project-directory naming, so the log sits beside the transcripts."""
    return cwd.replace("/", "-") or "-unknown"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        return 0
    # Slash commands are harness invocations, not directives.
    if prompt.startswith("/"):
        return 0
    cwd = payload.get("cwd") or os.getcwd()
    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session": payload.get("session_id", ""),
        "cwd": cwd,
        "prompt": prompt,
    }
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / f"{slug(cwd)}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
