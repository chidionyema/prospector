#!/usr/bin/env python3
"""Every PASS the engine produced should be on the shelf. Count the ones that are not.

READ-ONLY. Written to be run by the SessionStart state probe, so it never writes, never
imports anything that touches `store/` at import time, and answers inside a few seconds.

WHY THIS EXISTS
---------------
`tools/verify_selling_catalogue.py` checks the shelf INWARD: is every pack on sale backed by
a PASS dossier? That catches a pack selling on a KILL. It cannot catch the opposite, and the
opposite is what actually happened.

Measured 2026-08-13: the live catalogue had served exactly 50 packs for three days while the
engine held 74 passes. Twenty-four had been published UNLISTED and forgotten. Every mechanism
involved behaved "correctly" and silently:

  * `artifacts.py:452` turns a provider outage into an empty string so one dead call cannot
    lose the other three — then `run.py` published the empty pack without looking (fixed
    2026-08-13; `run.py::_generate_pack_content`). 12 packs.
  * The citation-liveness fence could not reach its own archive escape hatch, so live packs
    read as dead-linked (fixed 2026-08-13). 11 packs.
  * One pass was never published at all.

Nothing raised. Nothing alerted. The shelf simply stopped growing, and the only reason anyone
noticed is that a human counted the cards on the website. That is the defect this script
exists to make impossible: the gap between "the engine passed it" and "a buyer can buy it" is
now a number that a probe prints every session.

EXIT CODES
    0  every PASS is on the shelf
    1  at least one PASS is stranded  (the reasons are printed, one per line)
    2  the shelf could not be read — UNKNOWN, not a failure. A probe that turns "could not
       look" into a red line trains the reader to ignore it.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG_URL = os.environ.get("PROSPECTOR_CATALOG_URL", "https://api.mumchimp.com/catalog")


def _store(repo: str) -> str:
    """The store directory for `repo` — `PROSPECTOR_STORE_DIR` first, `<repo>/store` otherwise.

    A store path derived from `__file__` follows the CODE, not the state. Production moved to
    its own checkout on 2026-08-17 with `PROSPECTOR_STORE_DIR` pinned back at the canonical
    store, so `<code checkout>/store/prospector.db` does not exist there. This script read
    exactly that path and the live tick's recovery step failed every cycle with
    `sqlite3.OperationalError: unable to open database file`.

    The same resolution `prospector.config.store_root` and `tools/recover_stranded_passes.py`
    already use, spelled with `os` rather than imported, because this script is run by the
    SessionStart probe and must not import anything that touches `store/` at import time.
    """
    return os.environ.get("PROSPECTOR_STORE_DIR", "").strip() or os.path.join(repo, "store")


def _shelf_ids(timeout_s: float = 4.0) -> set[str]:
    """The ids a buyer can actually see. Raises on any failure — the caller maps that to 2.

    Four seconds, not ten. The state probe that runs this has a hard 30s ceiling above which
    it is KILLED and the whole live-state block is replaced by a timeout notice — measured at
    26s with this check at a 10s network budget, i.e. one slow response away from taking the
    probe down. A shelf we could not reach in four seconds is UNKNOWN, and UNKNOWN costs one
    line; a dead probe costs every line.
    """
    with urllib.request.urlopen(CATALOG_URL, timeout=timeout_s) as resp:
        rows = json.loads(resp.read())
    # The API projects PascalCase; be indifferent to it rather than pin a casing that a
    # serialiser setting can change under us.
    return {(r.get("Id") or r.get("id") or "") for r in rows}


def _passes(repo: str) -> list[tuple[str, str]]:
    """(candidate_id, created_at) for every live PASS, from the index the engine reads.

    The SQLite index, not a glob of `store/dossiers/*.pass.json`: the two disagree (measured
    2026-08-05, 113 files vs 158 rows) and the engine works from the index. Tombstoned rows
    are excluded for the same reason `_cmd_resume` excludes them — no dossier JSON stands
    behind them, so they can never be republished and would only inflate the number.
    """
    uri = f"file:{_store(repo)}/prospector.db?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=5.0) as conn:
        has_tomb = any(r[1] == "tombstone" for r in conn.execute("PRAGMA table_info(dossiers)"))
        live = " AND tombstone IS NULL" if has_tomb else ""
        return list(conn.execute(
            "SELECT candidate_id, created_at FROM dossiers "
            f"WHERE decision='pass' AND (provisional IS NULL OR provisional=0){live} "
            "ORDER BY created_at"))


def _why(repo: str, cid: str) -> str:
    """The blocking reason, read from the pack's own lint record — never inferred.

    `store/dossiers/<id>.lint.json` is what the publish path itself wrote when it held the
    pack back, so this reports the engine's finding rather than a second opinion about it.
    """
    path = f"{_store(repo)}/dossiers/{cid}.lint.json"
    try:
        with open(path) as fh:
            d = json.load(fh)
    except FileNotFoundError:
        return "never published (no lint record)"
    except Exception as exc:                       # noqa: BLE001 - a probe never dies here
        return f"lint record unreadable ({type(exc).__name__})"

    gaps = []
    if not d.get("pack_complete", True):
        probs = d.get("completeness_problems") or []
        empty = sum(1 for p in probs if "produced nothing" in str(p))
        gaps.append(f"content incomplete ({empty} empty artifact(s), {len(probs)} gap(s))")
    if d.get("bundle_missing"):
        gaps.append(f"bundle missing {len(d['bundle_missing'])} file(s)")
    if not d.get("ok", True):
        errs = [p for p in (d.get("problems") or []) if p.get("severity") == "error"]
        checks = sorted({p.get("check", "?") for p in errs})
        gaps.append(f"lint blocked ({len(errs)} error(s): {', '.join(checks)})")
    if not gaps:
        # Clean on disk and still not on the shelf: it only needs publishing. This is the
        # cheapest possible state to be in and the easiest to overlook, which is exactly why
        # it gets named rather than folded into "other".
        return "READY — lints clean and complete, just never published"
    return "; ".join(gaps)


def main() -> int:
    try:
        shelf = _shelf_ids()
    except Exception as exc:                       # noqa: BLE001
        print(f"shelf unreadable: {type(exc).__name__}: {exc}")
        return 2

    stranded = [(cid, created) for cid, created in _passes(REPO) if cid not in shelf]
    print(f"shelf packs: {len(shelf)}")
    print(f"stranded passes: {len(stranded)}")
    for cid, created in stranded:
        print(f"[{cid}] {str(created)[:10]}  {_why(REPO, cid)}")
    return 1 if stranded else 0


if __name__ == "__main__":
    sys.exit(main())
