"""
publish.py — Publish a PASS to own store + syndicate (Part 6, 11).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# We assume this is run from the repo root so prospector is importable
try:
    from prospector.bridge import EngineBridge
    from prospector.models import Decision
except ImportError:
    # Fallback for direct execution if needed
    pass


def publish(dossier: Any, cfg: Any) -> Dict[str, Any]:
    """
    Publish a dossier on PASS (Part 6, 11).
    Now uses EngineBridge to bundle artifacts and push to the Track 1 Store.
    On success, also writes a local ``store/listings/<id>.json`` receipt so the
    Control Center catalogue can show Pub=Y. Sellable source of truth remains
    the Store Catalog API.
    """
    # Handle both Dossier object and dict
    if hasattr(dossier, "decision"):
        decision = dossier.decision
        candidate_id = dossier.candidate.candidate_id
        title = getattr(dossier.candidate, "title", "") or ""
        market = getattr(dossier.candidate, "market", "") or ""
        created_at = getattr(dossier, "created_at", "") or ""
    elif isinstance(dossier, dict):
        decision_val = str(dossier.get("decision", "kill")).lower()
        decision = Decision.PASS if decision_val == "pass" else Decision.KILL
        cand = dossier.get("candidate") or {}
        candidate_id = cand.get("candidate_id", "unknown")
        title = cand.get("title", "") or ""
        market = cand.get("market", "") or ""
        created_at = dossier.get("created_at", "") or ""
    else:
        return {"status": "error", "reason": "Invalid dossier type"}

    if decision != Decision.PASS:
        return {"status": "skipped", "reason": f"Decision is {decision}"}

    # The catalog push and the local receipt are two writes with a gap between them. A crash
    # or kill inside that gap leaves a pack LIVE in the catalog with no local trace, and the
    # backfill — which decides what is outstanding purely from store/listings/ — would then
    # regenerate and re-publish it. The marker makes that window observable: it is written
    # before the push and cleared after the receipt, so anything left behind names exactly
    # which candidate to reconcile against the catalog.
    marker = _mark_inflight(candidate_id, cfg)

    # Use the new EngineBridge for Track 1 (Paddle + Catalog API)
    # The marker is cleared ONLY once the receipt exists, i.e. once local and catalog state
    # are known to agree. An exception or a reported failure leaves it in place on purpose:
    # a partial catalog update is indistinguishable from no update from here, and a stale
    # marker asking for a check is safer than a silent divergence.
    bridge = EngineBridge(cfg)
    success = bridge.publish_pass(dossier)

    if success:
        listing_path = _write_listing(
            candidate_id,
            {
                "candidate_id": candidate_id,
                "title": title,
                "market": market,
                "verified_at": created_at,
                "published_via": "EngineBridge",
                # Thin receipt — full sellable pack lives in the Store Catalog.
                "catalog": True,
            },
            cfg,
        )
        _clear_inflight(marker)
        return {
            "status": "published",
            "candidate_id": candidate_id,
            "method": "EngineBridge (Track 1)",
            "listing_path": str(listing_path),
        }
    else:
        return {
            "status": "failed",
            "candidate_id": candidate_id,
            "reason": "EngineBridge publication failed"
        }


def _store_dir(cfg: Any) -> Path:
    if isinstance(cfg, dict):
        store_dir_path = (cfg.get("store") or {}).get("dir") or cfg.get("store_dir", "store")
    else:
        store = getattr(cfg, "store", None) or {}
        store_dir_path = (
            store.get("dir") if isinstance(store, dict) else None
        ) or getattr(cfg, "store_dir", "store")
    return Path(store_dir_path or "store")


def inflight_dir(cfg: Any) -> Path:
    return _store_dir(cfg) / "listings" / ".inflight"


def _mark_inflight(candidate_id: str, cfg: Any) -> Optional[Path]:
    """Record 'a catalog push is about to happen for this id'. Best-effort: a failure to
    write the marker must never block a publish."""
    try:
        d = inflight_dir(cfg)
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{candidate_id}.json"
        p.write_text(json.dumps({"candidate_id": candidate_id, "pid": os.getpid()}))
        return p
    except Exception:
        return None


def _clear_inflight(marker: Optional[Path]) -> None:
    if marker is None:
        return
    try:
        marker.unlink(missing_ok=True)
    except Exception:
        pass


def unreconciled(cfg: Any) -> list:
    """Candidate ids that were mid-publish when a previous process died. Each one may be live
    in the catalog without a local receipt — check before re-publishing it."""
    d = inflight_dir(cfg)
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


# Every key a downstream consumer actually reads, and the type it reads it as.
_LISTING_SCHEMA: Dict[str, type] = {
    "candidate_id": str,
    "title": str,
    "market": str,
    "verified_at": str,
    "published_via": str,
    "catalog": bool,
}


def validate_listing(candidate_id: str, listing: Dict[str, Any]) -> None:
    """Raise ``ValueError`` unless ``listing`` is a real receipt for ``candidate_id``.

    Q4b.3. ``store/listings/`` is read as authority by three separate consumers — the
    Control Center Pub badge, ``tools/backfill_missing_listings.sh`` (which decides a pack
    is DONE purely from the presence of a file here) and ``decay._queue_unlist`` (which
    decides a killed pack was ever live) — and until now the writer accepted any dict at
    all. Two mock fixtures reached the directory that way and were counted as published
    packs by all three.

    Extra keys are allowed on purpose: adding a field to the receipt should not require
    editing a fence, and an unknown key cannot make a consumer mistake a non-pack for a
    pack. What is checked is that every key a consumer actually reads is present, is the
    right type, and — for ``candidate_id`` — agrees with the filename the receipt is about
    to be written to, because a receipt filed under the wrong id is how the backfill skips
    one pack forever while re-publishing another.

    This raises rather than dropping the write. The only caller builds the dict as a
    literal, so a violation is a code change, not bad data: the loud failure leaves
    ``publish()``'s in-flight marker in place, which is precisely the "catalog and local
    state may disagree, go reconcile" signal that marker exists to raise.
    """
    if not isinstance(listing, dict):
        raise ValueError(f"listing receipt must be a dict, got {type(listing).__name__}")

    missing = [k for k in _LISTING_SCHEMA if k not in listing]
    if missing:
        raise ValueError(
            f"listing receipt for {candidate_id!r} is missing required field(s): "
            f"{', '.join(sorted(missing))}")

    for key, expected in _LISTING_SCHEMA.items():
        if not isinstance(listing[key], expected):
            raise ValueError(
                f"listing receipt for {candidate_id!r} field {key!r} must be "
                f"{expected.__name__}, got {type(listing[key]).__name__}")

    if not candidate_id:
        raise ValueError("listing receipt needs a non-empty candidate_id")
    if listing["candidate_id"] != candidate_id:
        raise ValueError(
            f"listing receipt candidate_id {listing['candidate_id']!r} does not match the "
            f"file it is being written as ({candidate_id!r})")


def _write_listing(candidate_id: str, listing: Dict[str, Any], cfg: Any) -> Path:
    """Write a local listing receipt under ``store/listings/`` (CC Pub badge).

    Written atomically (temp file + os.replace): the receipt is what the backfill reads to
    decide a pack is done, so a torn half-written file would make it skip a pack forever.

    Validated BEFORE the temp file is opened — a rejected receipt must leave no trace at
    all, not a ``.tmp`` for the next reader to trip over.
    """
    validate_listing(candidate_id, listing)

    if isinstance(cfg, dict):
        store_dir_path = (cfg.get("store") or {}).get("dir") or cfg.get("store_dir", "store")
    else:
        store = getattr(cfg, "store", None) or {}
        store_dir_path = (
            store.get("dir") if isinstance(store, dict) else None
        ) or getattr(cfg, "store_dir", "store")
    store_dir = Path(store_dir_path or "store")
    listings_dir = store_dir / "listings"
    listings_dir.mkdir(parents=True, exist_ok=True)

    path = listings_dir / f"{candidate_id}.json"
    tmp = listings_dir / f".{candidate_id}.json.tmp"
    tmp.write_text(json.dumps(listing, indent=2, ensure_ascii=False))
    os.replace(tmp, path)
    return path


if __name__ == "__main__":
    # Example: load a dossier from store/ and publish it
    from prospector.config import load_config
    
    if len(sys.argv) < 2:
        print("Usage: python -m publish.publish <dossier_json_path> [config_yaml_path]")
        sys.exit(1)

    dossier_path = Path(sys.argv[1])
    cfg = load_config(sys.argv[2] if len(sys.argv) > 2 else None)

    with open(dossier_path, "r", encoding="utf-8") as f:
        dossier_dict = json.load(f)
    
    result = publish(dossier_dict, cfg)
    print(json.dumps(result, indent=2))
