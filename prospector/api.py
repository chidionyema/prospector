"""Headless read/commerce API (Part 15C).
Exposes Dossier, Pack, Listing, Claim, Entitlement as versioned JSON resources.
Teasers public, full dossiers entitlement-gated.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel

from .config import load_config
from .models import Decision
from .store import Store
from .telemetry import get_usage_summary

app = FastAPI(title="Prospector API", version="v1.0.0")
cfg = load_config()
store = Store(cfg)

# ---------------------------------------------------------------------------
# Entitlement (Part 15C)
# ---------------------------------------------------------------------------

def get_entitlements(authorization: Optional[str] = Header(None)) -> List[str]:
    """Check buyer entitlements. Stub: 'Bearer test-token' grants all."""
    if not authorization:
        return []
    if authorization == "Bearer test-token":
        return ["all"]
    # Real app would check a JWT or database for Stripe purchase state
    return []


def check_entitlement(candidate_id: str, entitlements: List[str]):
    """Refuse access if the buyer doesn't own this specific dossier."""
    if "all" in entitlements:
        return
    if candidate_id in entitlements:
        return
    raise HTTPException(status_code=403, detail="Entitlement required for full dossier")


# ---------------------------------------------------------------------------
# Resources (API v1)
# ---------------------------------------------------------------------------

@app.get("/v1/listings")
async def list_opportunities():
    """Public teaser listings (Scout tier)."""
    def _load():
        listings = []
        listings_dir = cfg.store_dir / "listings"
        if listings_dir.exists():
            for p in listings_dir.glob("*.json"):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    # Return only public teaser info
                    listings.append({
                        "id": data["candidate_id"],
                        "verified_at": data["verified_at"],
                        "reverify_due_at": data["reverify_due_at"],
                        "source_count": data["source_count"],
                        "scout": data["packs"]["scout"]
                    })
                except Exception:
                    continue
        return listings
    
    return await run_in_threadpool(_load)


@app.get("/v1/listings/{id}")
async def get_listing(id: str):
    """Specific public listing with all available pack info (prices/metadata)."""
    def _load():
        p = cfg.store_dir / "listings" / f"{id}.json"
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    
    data = await run_in_threadpool(_load)
    if data is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    return data


@app.get("/v1/dossiers/{id}")
async def get_dossier(id: str, entitlements: List[str] = Depends(get_entitlements)):
    """Full verification audit (gated)."""
    check_entitlement(id, entitlements)
    
    dossier_data = await run_in_threadpool(store.get, id)
    if not dossier_data:
        raise HTTPException(status_code=404, detail="Dossier not found")
    return dossier_data


@app.get("/v1/health")
async def health():
    return {"status": "ok", "version": "v1.0.0"}


@app.get("/v1/usage")
async def get_usage():
    """Token/call audit for this process — calls, tokens, cache hits per phase."""
    return get_usage_summary()


@app.get("/v1/metrics")
async def get_metrics():
    """Aggregated business and engine metrics."""
    def _calc():
        all_dossiers = store.all()
        total = len(all_dossiers)
        passes = sum(1 for d in all_dossiers if d["decision"] == "pass")
        defers = sum(1 for d in all_dossiers if d["decision"] == "defer")
        kills = total - passes - defers
        # Survival is computed over RULED dossiers only — deferrals (retrieval failures)
        # are not evidentiary kills and must not deflate the rate.
        ruled = passes + kills

        # Simple aggregation of kill-gates
        gates = {}
        for d in all_dossiers:
            if d["gate_fired"]:
                gates[d["gate_fired"]] = gates.get(d["gate_fired"], 0) + 1

        return {
            "engine": {
                "total_vetted": total,
                "pass_count": passes,
                "kill_count": kills,
                "defer_count": defers,
                "survival_rate": (passes / ruled) if ruled > 0 else 0
            },
            "gates": gates
        }
    
    return await run_in_threadpool(_calc)
