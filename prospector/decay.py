"""Decay loop (Part 7).
Re-verifies published dossiers when they exceed their SLA (reverify_due_at).
"""
from __future__ import annotations

import datetime
from typing import Optional

from .config import Config
from .models import Decision, Dossier
from .operator import Operator
from .retrieval import SearchProvider
from .run import vet_candidate
from .store import Store
from .telemetry import logger, set_context, track_latency


@track_latency(name="run_decay_loop")
def run_decay_loop(
    store: Store,
    op: Operator,
    search: SearchProvider,
    cfg: Config,
    now: Optional[datetime.datetime] = None
) -> dict[str, int]:
    """Check all PASS dossiers for staleness. Re-verify if due."""
    set_context(phase="decay_loop")
    logger.info("Starting decay loop re-verification")

    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    
    # Load all PASS dossiers
    all_pass = store.all(decision=Decision.PASS.value)
    
    refreshed = 0
    delisted = 0
    total_due = 0
    
    for row in all_pass:
        cid = row["candidate_id"]
        due_str = row["reverify_due_at"]
        if not due_str:
            continue
            
        due_dt = datetime.datetime.fromisoformat(due_str)
        if now < due_dt:
            continue
            
        total_due += 1
        set_context(candidate_id=cid)
        logger.info(f"Re-verifying due dossier: {row['title']!r}", extra={"candidate_id": cid})
        
        # Load full dossier
        d_dict = store.get(cid)
        if not d_dict:
            logger.warning(f"Dossier record missing for {cid}")
            continue
            
        # Re-verify using the candidate from the dossier
        from .models import Candidate
        cand = Candidate.from_dict(d_dict["candidate"])
        
        # Run full vet
        new_dossier = vet_candidate(cand, op, search, cfg, store=store)
        
        if new_dossier.decision == Decision.PASS:
            refreshed += 1
            logger.info("Dossier still valid. Date refreshed.", extra={"candidate_id": cid})
        else:
            delisted += 1
            logger.info(f"Dossier FAILED: {new_dossier.gate_fired}. Delisted.", 
                        extra={"candidate_id": cid, "gate": new_dossier.gate_fired})
            # store.save() already handled the delisting in the index by setting decision=KILL
            # and updating the path to .kill.json

    logger.info("Decay loop complete", extra={
        "total_due": total_due,
        "refreshed": refreshed,
        "delisted": delisted
    })
    return {
        "total_due": total_due,
        "refreshed": refreshed,
        "delisted": delisted
    }
