"""
publish.py — Publish a PASS to own store + syndicate (Part 6, 11).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# We assume this is run from the repo root so prospector is importable
try:
    from prospector.models import Dossier, Decision
    from prospector.bridge import EngineBridge
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

    # Use the new EngineBridge for Track 1 (Paddle + Catalog API)
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


def _write_listing(candidate_id: str, listing: Dict[str, Any], cfg: Any) -> Path:
    """Write a local listing receipt under ``store/listings/`` (CC Pub badge)."""
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
    path.write_text(json.dumps(listing, indent=2, ensure_ascii=False))
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
