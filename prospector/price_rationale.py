"""D3 — the derivation record behind every price decision.

`PATCH /internal/catalog/{id}/price` carries a one-line `Reason` and an optional
`RationaleRef` (`store_platform/src/Store.Api/Contracts/PricePatchRequest.cs:28`). The
Reason is what a human reads; the ref is what an auditor follows. This module writes what
the ref points at: the full inputs of one `PriceDecision`, the ladder that was actually in
force when it was taken, and when.

Three properties, each answering a specific way a price audit trail goes wrong:

* **The ladder is snapshotted, not named.** `config.yaml` is a live file; a record that
  said only "L1-ladder-2026-08-05" would be reinterpreted every time someone edits
  `rungs`, and the reader would silently get today's numbers for last month's decision.
  The record carries the numbers themselves, plus a `fingerprint` digest over them. The
  human-readable `version` label is recorded too, but it is a label — the fingerprint is
  what proves which ladder ran.
* **The record's own digest is in its path.** The ref is
  `…/<pack_id>/<timestamp>-<digest12>.json`, where the digest is taken over the record
  minus that field. An edited record no longer matches the ref that points at it, and
  `read_rationale` refuses it rather than returning quietly-wrong provenance.
* **No decision logic lives here.** This is serialisation. `pricing.price_for` decides;
  a second place that could compute a price is a second answer free to disagree with the
  one the buyer was charged.

Records are committed, not gitignored (unlike the rest of `store/`, which is daemon
runtime output). A price is a money-rail act, and an audit trail that exists only on the
machine that happened to run the write is not an audit trail.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from prospector.pricing import PriceDecision

SCHEMA_VERSION = 1

# Relative to the repo root, so the value stored in `RationaleRef` is portable: the API
# receives a path, not a URL, and an absolute path from whichever machine ran the write
# would be a pointer nobody else can follow.
RATIONALE_DIR = "store/pricing/rationale"

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Env override for the root the records live under, read at CALL time, never bound at
# import — `_AUDIT_DIR` was bound at import and `monkeypatch.setenv` on it was silently a
# no-op, which is how the test suite once appended real-looking rows to the production
# audit log. tests/conftest.py points this at a tmp dir for every test.
_ROOT_ENV = "PROSPECTOR_RATIONALE_ROOT"


def _root(repo_root: Optional[Path] = None) -> Path:
    return Path(repo_root or os.environ.get(_ROOT_ENV) or _REPO_ROOT)

# A pack id reaches here from a catalogue row and becomes a path segment. Anything
# outside this class is replaced rather than escaped, and `.` is deliberately NOT in it:
# a pack id of ".." would otherwise survive sanitisation intact and write the record one
# directory above the one it is supposed to live in.
_SAFE = re.compile(r"[^A-Za-z0-9_-]")


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _digest(obj: Any) -> str:
    return hashlib.sha256(_canonical(obj)).hexdigest()


def ladder_snapshot(cfg: Any) -> dict:
    """The pricing config that was actually in force, as data.

    Read defensively (`or {}`, no `[...]`): this runs on the publish path behind
    `price_for`, which itself degrades rather than raising on a partial ladder. A record
    writer that crashed on a config `price_for` tolerated would take publishing down to
    protect an audit log, which is backwards.
    """
    listing = getattr(cfg, "listing", None) or {}
    pricing = listing.get("pricing") or {}
    comparables = pricing.get("comparables") or {}
    snap = {
        "rungs": [int(r) for r in (pricing.get("rungs") or [])],
        "default_rung_index": pricing.get("default_rung_index"),
        "tier_rung_index": dict(pricing.get("tier_rung_index") or {}),
        "market_rung_offset": dict(pricing.get("market_rung_offset") or {}),
        "flat_price_pence": listing.get("price_pence"),
        "comparables": {
            "enabled": bool(comparables.get("enabled", False)),
            "rung_adjust_enabled": bool(comparables.get("rung_adjust_enabled", False)),
        },
    }
    snap["version"] = pricing.get("ladder_version")
    snap["fingerprint"] = "sha256:" + _digest(
        {k: v for k, v in snap.items() if k != "version"})[:16]
    return snap


def build_record(pack_id: str, decision: PriceDecision, cfg: Any, *,
                 actor: str, source: str, reason: Optional[str] = None,
                 at: Optional[datetime] = None) -> dict:
    """Assemble the record. Pure: no I/O, and `at` is injectable so tests pin the clock."""
    ts = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    record = {
        "schema_version": SCHEMA_VERSION,
        "pack_id": pack_id,
        "created_at": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "actor": actor,
        "source": source,
        "reason": reason,
        "decision": {
            "price_pence": int(decision.price_pence),
            "rung": decision.rung,
            "segment": dict(decision.segment or {}),
            "rationale": decision.rationale,
            "evidence": decision.evidence,
        },
        "ladder": ladder_snapshot(cfg),
    }
    record["content_digest"] = "sha256:" + _digest(record)
    return record


def record_ref(record: dict) -> str:
    """The repo-relative path this record belongs at — derived from the record alone.

    Deterministic: the same record always yields the same ref, so a re-run of a backfill
    overwrites its own record rather than accumulating near-identical ones, while any
    change to the decision (or to the ladder behind it) lands at a new path.
    """
    pack = _SAFE.sub("_", str(record.get("pack_id") or "unknown"))
    stamp = _SAFE.sub("_", str(record.get("created_at") or "").replace(":", ""))
    digest = str(record.get("content_digest") or "").split(":")[-1][:12]
    return f"{RATIONALE_DIR}/{pack}/{stamp}-{digest}.json"


def write_rationale(pack_id: str, decision: PriceDecision, cfg: Any, *,
                    actor: str, source: str, reason: Optional[str] = None,
                    at: Optional[datetime] = None,
                    repo_root: Optional[Path] = None) -> str:
    """Write the record and return the ref to put in `PricePatchRequest.RationaleRef`.

    The write is atomic (tmp + `os.replace`): a torn JSON file is worse than no file,
    because it reads as evidence right up until someone tries to parse it.
    """
    record = build_record(pack_id, decision, cfg, actor=actor, source=source,
                          reason=reason, at=at)
    ref = record_ref(record)
    path = _root(repo_root) / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)
    return ref


def read_rationale(ref: str, repo_root: Optional[Path] = None) -> dict:
    """Load a record by ref and prove it is the one the ref names.

    Raises `ValueError` on a digest mismatch. A rationale record is read precisely when
    someone is asking why a buyer was charged what they were charged; returning an edited
    record without a word is the one behaviour that would make this file worse than
    useless.
    """
    path = _root(repo_root) / ref
    record = json.loads(path.read_text(encoding="utf-8"))
    stated = record.get("content_digest")
    recomputed = "sha256:" + _digest(
        {k: v for k, v in record.items() if k != "content_digest"})
    if stated != recomputed:
        raise ValueError(
            f"rationale record at {ref} does not match its own digest "
            f"(stated {stated}, recomputed {recomputed}) — it has been edited since it "
            f"was written, and cannot be used as provenance for a price")
    return record
