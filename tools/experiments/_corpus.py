#!/usr/bin/env python3
"""Read-only accessors for the dossier corpus, shared by E12 / E15 / E17 / L1.

Every function here opens files for reading only. Nothing in this module writes into `store/`,
and the sqlite helper connects with `mode=ro` on a URI so the guarantee is enforced by the driver
rather than by convention.

One shape note that all four experiments depend on, verified on disk 2026-08-07:

    dossier
      candidate         {candidate_id, title, one_liner, who_pays, ...}
      gate_fired        str | null      e.g. "adversarial_decisive"
      decision          str
      created_at        ISO8601 str
      adversarial       {kill_case, decisive, confidence, citations[], provider, provisional}
      checks[]          {check_name, verdict, confidence, rationale, citations[],
                         queries[], sources[], retrieval_failed, degraded, provider, provisional}
      checks[].sources[] {source_id, url, text, query, fetched_at, published_at}

`citations` holds `source_id` hashes, NOT urls and NOT passage text. Resolving them against
`sources[]` is the difference between "the model named an id" and "the model pointed at a passage
we actually hold" — which is exactly what E12 measures.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

#: Env overrides so a MATCHED PAIR of experiments can be run against a frozen
#: snapshot instead of the live store. Two runs that must be compared to each
#: other (E15 vs E17) are otherwise racing the daemon: `corpus_fingerprint`
#: below documents the 2026-08-07 measurement where that race moved tau from
#: 0.0589 to 0.0691. The fingerprint DETECTS the race; these detect nothing and
#: PREVENT it. Freeze with `_freeze_corpus.py`, which prints the two exports.
ENV_CORPUS_DIR = "PROSPECTOR_CORPUS_DIR"
ENV_CORPUS_DB = "PROSPECTOR_CORPUS_DB"

MOAT = {"claude_cli", "claude", "claude-cli/default"}
RULED = {"supported", "refuted"}


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser() if raw else None


def corpus_dir() -> Path:
    """Where dossiers are read from. Resolved per call, never cached at import:
    a module-level constant would silently ignore an override set afterwards,
    and a constant that no longer describes what the code reads is the exact
    'write-only field' trap this repo has been bitten by before."""
    return _env_path(ENV_CORPUS_DIR) or (ROOT / "store" / "dossiers")


def db_path() -> Path:
    return _env_path(ENV_CORPUS_DB) or (ROOT / "store" / "prospector.db")


def is_frozen() -> bool:
    """True when this process is reading a snapshot rather than the live store.
    Receipts record it so a number can never be mistaken for a live reading."""
    return bool(_env_path(ENV_CORPUS_DIR) or _env_path(ENV_CORPUS_DB))


def dossier_paths() -> list[str]:
    return sorted(glob.glob(str(corpus_dir() / "*.json")))


def corpus_fingerprint() -> dict:
    """Identify the exact corpus state a run sampled.

    The dossier store is LIVE: the daemon rewrites `<id>.pass.json` / `<id>.kill.json` while an
    experiment runs. `dossier_paths()` is sorted, so sampling is deterministic against a FROZEN
    corpus -- but a re-vet that rewrites one dossier changes which checks are eligible, which
    shifts a systematic every-k-th sample, which moves any threshold calibrated on that sample.
    Measured 2026-08-07: two E15 runs 40 min apart over the same 2649-eligible population drew
    different samples and produced tau 0.0589 vs 0.0691 (rate 43.4% vs 48.9%). Recording this
    fingerprint is what makes two runs comparable instead of merely similar.
    """
    paths = dossier_paths()
    h = hashlib.sha256()
    newest = 0.0
    for path in paths:
        try:
            st = os.stat(path)
        except OSError:
            continue
        newest = max(newest, st.st_mtime)
        h.update(f"{os.path.basename(path)}:{st.st_size}:{int(st.st_mtime)}\n".encode())
    return {
        "n_dossiers": len(paths),
        "newest_mtime_utc": datetime.fromtimestamp(newest, tz=timezone.utc).isoformat()
        if newest else None,
        "sha256": h.hexdigest()[:16],
        "frozen": is_frozen(),
        "corpus_dir": str(corpus_dir()),
        "note": "sampling is deterministic against a frozen corpus; the store is live, so two "
                "runs with different fingerprints are different samples, not a repeat. "
                "frozen=true means this run read a snapshot, so a matched pair is guaranteed "
                "rather than hoped for; frozen=false means the daemon could move underneath it.",
    }


def iter_dossiers(paths: list[str] | None = None) -> Iterator[tuple[str, dict]]:
    """(path, dossier) for every parseable dossier. Unparseable files are skipped silently —
    they are counted by the caller via len(dossier_paths()) minus what it saw."""
    for path in (paths if paths is not None else dossier_paths()):
        try:
            with open(path) as fh:
                yield path, json.load(fh)
        except Exception:
            continue


def candidate_id(path: str, dossier: dict) -> str:
    cand = dossier.get("candidate") or {}
    return str(cand.get("candidate_id") or os.path.basename(path).split(".")[0])


def source_index(dossier: dict) -> dict[str, dict]:
    """source_id -> source object, across every check plus any top-level `sources`.

    Union across checks is correct here: the adversarial pass is shown ALL checks' verdicts
    (verify.py:643 serialises every CheckResult into its prompt), so a source_id from any check is
    a legitimate citation target for it.
    """
    index: dict[str, dict] = {}
    for chk in dossier.get("checks") or []:
        for src in chk.get("sources") or []:
            if isinstance(src, dict) and src.get("source_id"):
                index.setdefault(str(src["source_id"]), src)
    for src in dossier.get("sources") or []:
        if isinstance(src, dict) and src.get("source_id"):
            index.setdefault(str(src["source_id"]), src)
    return index


def cited_sources(chk: dict, index: dict[str, dict] | None = None) -> tuple[list[dict], list[str]]:
    """(resolved source objects, unresolved citation ids) for one check or adversarial object."""
    idx = index if index is not None else {
        str(s["source_id"]): s for s in (chk.get("sources") or [])
        if isinstance(s, dict) and s.get("source_id")}
    resolved, dangling = [], []
    for cid in chk.get("citations") or []:
        key = str(cid)
        if key in idx:
            resolved.append(idx[key])
        else:
            dangling.append(key)
    return resolved, dangling


def db_query(sql: str, params: tuple = ()) -> list[tuple]:
    """READ-ONLY sqlite. `mode=ro` makes any write attempt an error from the driver, so this
    cannot be the thing that mutates production state."""
    db = db_path()
    if not db.exists():
        return []
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()          # `with sqlite3.connect(...)` commits, it does NOT close


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval. Normal-approx CIs go out of [0,1] and lie badly on small n or on
    rates near 0 or 1, which is exactly where these audits live."""
    if n <= 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))
