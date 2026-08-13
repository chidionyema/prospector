#!/usr/bin/env python3
"""The reviewer's surface for the human verification layer (programme doc §33.8, item 33-G).

Without this file the layer is the defect class memory calls `built-and-unreachable`: a fence, a
receipt format and a test suite that no human can actually operate. Four commands:

    backfill [--write]        trace figures in dossiers already on disk. ZERO LLM calls.
    list [--pending-only]     every PASS pack with its verification status
    show <pack_id>            the flagged figures with the prose and sources to judge them
    decide <pack_id> <key> <action> --reviewer NAME [--note "..."]

**Why `backfill` exists and is the first command.** All 87 PASS dossiers on disk predate
`CheckResult.untraceable_figures`, so they read `untraced` and the review queue would be empty —
the layer would ship with nothing to review while 15 packs sell with untraceable figures. But the
trace needs no model: the dossier already stores each check's rationale, its citations and the
passages retrieved, and `verify.py` built the verdict prompt from exactly those passages truncated
to 600 chars. So the trace can be recomputed from the record itself, offline, deterministically.

`backfill --write` adds ONLY the `untraceable_figures` key to each check in the dossier JSON, atomically.
It is derived from that record's own content and it changes no ruling — but it does touch an audit
artifact, so it prints every change and requires the explicit flag.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prospector import figure_check, human_review  # noqa: E402
from prospector.config import load_config  # noqa: E402


class _Src:
    """The dossier stores sources as dicts; the tracer wants `.source_id` / `.text`."""

    def __init__(self, d: dict) -> None:
        self.source_id = str(d.get("source_id") or "")
        self.text = str(d.get("text") or "")


def _dossier_files(cfg) -> list[Path]:
    root = Path(getattr(cfg, "store_dir", "store")) / "dossiers"
    return sorted(p for p in root.glob("*.pass.json") if p.is_file())


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _pack_id(d: dict, path: Path) -> str:
    return str((d.get("candidate") or {}).get("candidate_id") or path.name.split(".")[0])


def _rungs(cfg) -> set[str]:
    listing = getattr(cfg, "listing", None) or {}
    return figure_check.price_rung_forms((listing.get("pricing") or {}).get("rungs") or [])


def _trace_check(check: dict, dossier: dict, rungs: set[str]) -> list[str]:
    """Recompute one check's untraceable figures from the stored record.

    Passages come from the CHECK's own sources when it has them, falling back to the dossier's
    pooled sources — the same union the tracer buckets as cited vs other_passage.
    """
    raw = check.get("sources") or dossier.get("sources") or []
    sources = [_Src(s) for s in raw if isinstance(s, dict)]
    return figure_check.trace_figures(
        str(check.get("rationale") or ""),
        sources,
        [str(c) for c in (check.get("citations") or [])],
        self_text=json.dumps(dossier.get("candidate") or {}),
        price_rungs=rungs,
        truncate=figure_check.DEFAULT_TRUNCATE,
    ).untraceable


def cmd_backfill(cfg, args) -> int:
    rungs = _rungs(cfg)
    dirty = clean = skipped = 0
    for path in _dossier_files(cfg):
        d = _load(path)
        checks = d.get("checks") or []
        if not checks:
            skipped += 1
            continue
        if human_review.is_traced(checks) and not args.force:
            skipped += 1
            continue
        flagged: list[str] = []
        for c in checks:
            u = _trace_check(c, d, rungs)
            c["untraceable_figures"] = u          # [] is a positive claim; the trace just ran
            flagged += [f"{c.get('check_name')}:{f}" for f in u]
        if flagged:
            dirty += 1
            print(f"{_pack_id(d, path)}  {len(flagged)} flagged: {', '.join(flagged)}")
        else:
            clean += 1
        if args.write:
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, path)
    verb = "WROTE" if args.write else "would write (dry run; pass --write)"
    print(f"\n{verb}: {dirty} pack(s) with flagged figures, {clean} clean, {skipped} skipped.")
    return 0


def _queue(cfg, path: Path) -> tuple[str, dict, list[human_review.Item], str, list[str]]:
    d = _load(path)
    pid = _pack_id(d, path)
    items, traced = human_review.queue_from_checks(d.get("checks") or [])
    st, outstanding = human_review.status(pid, items, traced=traced,
                                         root=human_review.root_for(cfg))
    return pid, d, items, st, outstanding


def cmd_list(cfg, args) -> int:
    counts: dict[str, int] = {}
    for path in _dossier_files(cfg):
        pid, _d, items, st, outstanding = _queue(cfg, path)
        counts[st] = counts.get(st, 0) + 1
        if args.pending_only and st in human_review.SELLABLE:
            continue
        note = f" ({len(outstanding)} outstanding)" if outstanding else ""
        print(f"{pid}  {st}{note}")
    print("\n" + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if counts.get(human_review.STATUS_UNTRACED):
        print("untraced packs have never been figure-traced — run `backfill --write` first.")
    return 0


def cmd_show(cfg, args) -> int:
    for path in _dossier_files(cfg):
        pid, d, items, st, outstanding = _queue(cfg, path)
        if pid != args.pack_id:
            continue
        print(f"{pid}  status={st}  queued={len(items)}  outstanding={len(outstanding)}\n")
        by_check: dict[str, list[str]] = {}
        for it in items:
            by_check.setdefault(it.check, []).append(it.figure)
        for c in d.get("checks") or []:
            name = str(c.get("check_name") or "")
            figs = by_check.get(name)
            if not figs:
                continue
            print(f"--- {name} ({c.get('verdict')}, conf {c.get('confidence')})")
            print(f"    figures with no retrieved passage: {', '.join(figs)}")
            print(f"    rationale: {c.get('rationale')}")
            for s in (c.get("sources") or [])[:6]:
                print(f"    source [{s.get('source_id')}] {s.get('url')}")
            print(f"    keys: {', '.join(f'{name}:{f}' for f in figs)}\n")
        print(f"decide with: review_figures.py decide {pid} <key> "
              f"<{'|'.join(sorted(human_review.ACTIONS))}> --reviewer YOU --note '...'")
        return 0
    print(f"no PASS dossier for {args.pack_id!r}", file=sys.stderr)
    return 2


def cmd_decide(cfg, args) -> int:
    for path in _dossier_files(cfg):
        pid, _d, items, _st, _out = _queue(cfg, path)
        if pid != args.pack_id:
            continue
        try:
            human_review.record_decision(pid, items, args.key, args.action, args.reviewer,
                                        args.note, root=human_review.root_for(cfg))
        except ValueError as e:
            print(f"refused: {e}", file=sys.stderr)
            return 2
        st, outstanding = human_review.status(pid, items, traced=True,
                                             root=human_review.root_for(cfg))
        print(f"recorded. {pid} is now {st}"
              + (f", {len(outstanding)} outstanding: {', '.join(outstanding)}" if outstanding else ""))
        return 0
    print(f"no PASS dossier for {args.pack_id!r}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default="config.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("backfill", help="trace figures in stored dossiers (no LLM calls)")
    b.add_argument("--write", action="store_true", help="mutate the dossier JSON, not just report")
    b.add_argument("--force", action="store_true", help="re-trace dossiers already traced")

    ls = sub.add_parser("list", help="verification status of every PASS pack")
    ls.add_argument("--pending-only", action="store_true")

    s = sub.add_parser("show", help="the flagged figures for one pack, with prose and sources")
    s.add_argument("pack_id")

    dd = sub.add_parser("decide", help="record one human decision")
    dd.add_argument("pack_id")
    dd.add_argument("key", help="check:figure, as printed by `show`")
    dd.add_argument("action", choices=sorted(human_review.ACTIONS))
    dd.add_argument("--reviewer", required=True)
    dd.add_argument("--note", default="")

    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    return {"backfill": cmd_backfill, "list": cmd_list,
            "show": cmd_show, "decide": cmd_decide}[args.cmd](cfg, args)


if __name__ == "__main__":
    raise SystemExit(main())
