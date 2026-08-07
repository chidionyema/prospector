"""Headless read/commerce API (Part 15C).
Exposes Dossier, Pack, Listing, Claim, Entitlement as versioned JSON resources.
Teasers public, full dossiers entitlement-gated.
"""
from __future__ import annotations

import hmac
import json
import os
import re
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from starlette.concurrency import run_in_threadpool

from .config import load_config
from .store import Store
from .telemetry import get_usage_summary, logger

app = FastAPI(title="Prospector API", version="v1.0.0")
cfg = load_config()
store = Store(cfg)

# ---------------------------------------------------------------------------
# Entitlement (Part 15C)
# ---------------------------------------------------------------------------

def get_entitlements(authorization: Optional[str] = Header(None)) -> List[str]:
    """Check buyer entitlements.

    The dev all-access token is INERT unless PROSPECTOR_DEV_ALL_ACCESS_TOKEN is set
    (P2 — closes the hardcoded `Bearer test-token` backdoor). In production the env var
    is absent, so this grants nothing and the real entitlement path (JWT / purchase
    state) governs. Read at request time so tests can opt in via the env var.
    """
    if not authorization:
        return []
    dev_token = os.environ.get("PROSPECTOR_DEV_ALL_ACCESS_TOKEN")
    if dev_token and authorization == f"Bearer {dev_token}":
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


# Candidate/dossier/listing ids are the engine's content ids: sha1[:16] (see models._id),
# i.e. exactly 16 lowercase hex chars. Any id reaching the filesystem MUST match this — an
# unvalidated `{id}` lets `../` traversal read arbitrary .json files (cached grounding
# passages, the store db) the process can reach. Validate before touching the store.
_ID_RE = re.compile(r"^[0-9a-f]{16}$")


def validate_id(id: str) -> str:
    """Reject any id that is not a well-formed engine content id (anti path-traversal)."""
    if not _ID_RE.fullmatch(id):
        raise HTTPException(status_code=400, detail="Invalid id")
    return id


def require_admin(x_admin_key: Optional[str] = Header(None)) -> None:
    """Gate operational endpoints (usage/metrics) behind an admin key.

    Fail closed: if PROSPECTOR_ADMIN_API_KEY is unset, the operational endpoints are not
    exposed at all (503), so leaving it unconfigured in production cannot leak provider mix,
    token volume, cost, or vetting rates. When set, the X-Admin-Key header must match it
    (timing-safe compare).
    """
    expected = os.environ.get("PROSPECTOR_ADMIN_API_KEY")
    if not expected:
        raise HTTPException(status_code=503, detail="Operational API not configured")
    if not x_admin_key or not hmac.compare_digest(x_admin_key, expected):
        raise HTTPException(status_code=401, detail="Admin authentication required")


# ---------------------------------------------------------------------------
# Resources (API v1)
# ---------------------------------------------------------------------------

@app.get("/v1/listings")
async def list_opportunities():
    """Public teaser listings (Scout tier).

    The shape served here is the receipt `publish._write_listing` actually writes.
    Until 2026-08-07 it read `reverify_due_at`, `source_count` and `packs["scout"]` —
    three keys NOTHING in this repo has ever written — and the bare
    `except Exception: continue` below turned every resulting `KeyError` into a silent
    skip. Measured over the operator's real store, every receipt and not a sample:
    73 of 73 lacked all three, so the endpoint answered **200 with `[]` for the entire
    live catalogue**, and had done for its whole life (programme doc §28.10).

    The test suite could not see it: `tests/integration/test_api.py`'s fixture wrote a
    receipt carrying those keys plus a three-tier `packs` block — a shape production has
    never produced. The endpoint was only ever exercised against a shape invented to
    exercise it.

    Two properties are therefore load-bearing here, not stylistic:

    * `candidate_id`/`title`/`market`/`verified_at` are REQUIRED — a receipt missing one
      is not a teaser and is skipped. `published_via`/`catalog` are provenance, not
      teaser content, so a receipt missing one is still served: dropping a real listing
      over a bookkeeping key is the failure this docstring exists to describe.
    * Skips are COUNTED AND LOGGED. A total schema divergence must never again be
      indistinguishable, to a caller or to a log reader, from an empty catalogue.

    `packs` is deliberately not restored: it is the deleted 3-tier pricing shape
    (`test_api.py:19-21` records `compose_packs` as removed, orphaned, never called in
    production), and reviving it would resurrect an abandoned model.
    """
    def _load():
        listings = []
        skipped: list[str] = []
        listings_dir = cfg.store_dir / "listings"
        if listings_dir.exists():
            for p in sorted(listings_dir.glob("*.json")):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    listings.append({
                        "id": data["candidate_id"],
                        "title": data["title"],
                        "market": data["market"],
                        "verified_at": data["verified_at"],
                        "published_via": data.get("published_via"),
                        "catalog": data.get("catalog"),
                    })
                except Exception as exc:
                    skipped.append(f"{p.name}: {type(exc).__name__}: {exc}")
        if skipped:
            logger.warning(
                "/v1/listings served %d listing(s) and SKIPPED %d unreadable receipt(s) "
                "— first %d: %s",
                len(listings), len(skipped), min(5, len(skipped)), "; ".join(skipped[:5]),
            )
        return listings

    return await run_in_threadpool(_load)


@app.get("/v1/listings/{id}")
async def get_listing(id: str):
    """Specific public listing with all available pack info (prices/metadata)."""
    validate_id(id)
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
    validate_id(id)
    check_entitlement(id, entitlements)
    
    dossier_data = await run_in_threadpool(store.get, id)
    if not dossier_data:
        raise HTTPException(status_code=404, detail="Dossier not found")
    return dossier_data


@app.get("/v1/health")
async def health():
    return {"status": "ok", "version": "v1.0.0"}


@app.get("/v1/usage")
async def get_usage(_: None = Depends(require_admin)):
    """Token/call audit for this process — calls, tokens, cache hits per phase."""
    return get_usage_summary()


@app.get("/v1/metrics")
async def get_metrics(_: None = Depends(require_admin)):
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
