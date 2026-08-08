#!/usr/bin/env python3
"""Freeze the live dossier corpus so a MATCHED PAIR of experiments is guaranteed.

WHY
---
`_corpus.corpus_fingerprint()` detects that two runs saw different corpora. It
cannot prevent it. On 2026-08-07 E15 and E17 both reported `n_dossiers: 1597`
and were quoted as a pair, but their fingerprints were `d97829ed7ea0bae0`
(20:16:23Z) and `81d96e5387f7467a` (20:35:10Z) — nineteen minutes apart, same
count, different content, because the daemon re-vets and rewrites dossiers while
an experiment runs. Any agreement figure computed across them compares two
samples, not two methods.

This script takes a snapshot and prints the two exports that point the harnesses
at it. Both halves of a pair then read byte-identical inputs and their
fingerprints match by construction rather than by luck.

INTEGRITY
---------
The snapshot is verified, not assumed: the live corpus is fingerprinted before
the copy and the SNAPSHOT is fingerprinted after it. If they differ, the daemon
wrote during the copy and the snapshot is internally torn, so it retries. A torn
snapshot is worse than no snapshot — it looks frozen and is not.

USAGE
-----
    eval "$(.venv/bin/python tools/experiments/_freeze_corpus.py)"
    .venv/bin/python tools/experiments/runner.py run E15 --all
    .venv/bin/python tools/experiments/runner.py run E17 --all
    # both receipts now carry frozen=true and the SAME corpus_fingerprint.sha256
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _corpus as corpus  # noqa: E402  - sibling helper, path set above

MAX_ATTEMPTS = 3


def _live_fingerprint() -> dict:
    """Fingerprint the LIVE store, ignoring any override already in the env —
    otherwise freezing from inside a frozen shell would just re-copy the snapshot
    and report a perfect match that proves nothing."""
    saved = {k: os.environ.pop(k, None)
             for k in (corpus.ENV_CORPUS_DIR, corpus.ENV_CORPUS_DB)}
    try:
        return corpus.corpus_fingerprint()
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def freeze(dest: Path | None = None) -> tuple[Path, dict]:
    """Copy the live corpus to `dest`. Returns (dest, verified fingerprint).

    Raises RuntimeError if the corpus keeps moving — the caller must not receive
    a snapshot that quietly differs from what it was asked to freeze.
    """
    saved = {k: os.environ.pop(k, None)
             for k in (corpus.ENV_CORPUS_DIR, corpus.ENV_CORPUS_DB)}
    try:
        live_db = corpus.db_path()
        for attempt in range(1, MAX_ATTEMPTS + 1):
            before = _live_fingerprint()
            target = dest or Path(tempfile.gettempdir()) / f"prospector-corpus-{before['sha256']}"
            snap_dir = target / "dossiers"
            if snap_dir.exists():
                shutil.rmtree(snap_dir)
            snap_dir.mkdir(parents=True, exist_ok=True)
            for src in corpus.dossier_paths():
                # copy2 preserves mtime and size, which is what the fingerprint
                # hashes -- so a faithful snapshot reproduces the hash exactly.
                shutil.copy2(src, snap_dir / os.path.basename(src))
            if live_db.exists():
                shutil.copy2(live_db, target / "prospector.db")

            os.environ[corpus.ENV_CORPUS_DIR] = str(snap_dir)
            after = corpus.corpus_fingerprint()
            del os.environ[corpus.ENV_CORPUS_DIR]

            if after["sha256"] == before["sha256"]:
                return target, after
            print(f"# attempt {attempt}: corpus moved during the copy "
                  f"({before['sha256']} -> {after['sha256']}); retrying",
                  file=sys.stderr)
        raise RuntimeError(
            f"corpus did not hold still across {MAX_ATTEMPTS} attempts; the daemon is "
            f"writing faster than the snapshot completes. Pause it, or accept that no "
            f"matched pair can be taken right now -- do NOT quote an unmatched pair."
        )
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="freeze the dossier corpus for a matched pair")
    ap.add_argument("--dest", type=Path, default=None,
                    help="snapshot directory (default: a temp dir named for the fingerprint)")
    ns = ap.parse_args(argv)

    target, fp = freeze(ns.dest)
    print(f"# frozen corpus: {fp['n_dossiers']} dossiers, sha256={fp['sha256']}", file=sys.stderr)
    print(f"# newest mtime : {fp['newest_mtime_utc']}", file=sys.stderr)
    print(f"export {corpus.ENV_CORPUS_DIR}={target / 'dossiers'}")
    db = target / "prospector.db"
    if db.exists():
        print(f"export {corpus.ENV_CORPUS_DB}={db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
