"""Lightweight pre-screen gate (Part 3).

Biased toward keeping candidates — uncertainty defaults to keep=True so that
novel, unconventional opportunities are never silently dropped. Only an
explicit model-level keep=false triggers rejection.
"""
from __future__ import annotations

import json

from .config import Config
from .models import Candidate
from .operator import Operator
from .prompts import render
from .telemetry import logger, track_latency


@track_latency(name="prescreen")
def prescreen(
    op: Operator,
    cfg: Config,
    cand: Candidate,
) -> tuple[bool, str]:
    """Ask the model whether a candidate is worth pursuing further.

    Returns:
        (keep, reason) — keep is True unless the model explicitly says False.

    Critical invariant (Part 3): bias toward keep. On ANY exception, parse
    failure, or ambiguous output, return (True, "kept on uncertainty") so that
    novel ideas are never silently discarded.
    """
    logger.info(f"Prescreening candidate: {cand.title!r}", extra={"candidate_id": cand.candidate_id})
    try:
        system, user = render("prescreen", candidate_json=json.dumps(cand.to_dict()))
        data = op.complete_json(system, user)
    except Exception as e:
        logger.warning(f"Prescreen failed for {cand.title!r}: {e}", extra={"error": str(e)})
        return True, "kept on uncertainty"

    # Guard: non-dict response is treated as ambiguous.
    if not isinstance(data, dict):
        logger.warning(f"Prescreen returned non-dict response for {cand.title!r}", extra={"response": str(data)})
        return True, "kept on uncertainty"

    raw_keep = data.get("keep")

    # Only reject on an explicit falsy value — anything else keeps.
    if raw_keep is False or (isinstance(raw_keep, str) and raw_keep.lower() == "false"):
        reason = str(data.get("reason", "")) or "pre-screen rejected"
        logger.info(f"PRESCREEN REJECTED: {cand.title!r}", extra={"reason": reason})
        return False, reason

    reason = str(data.get("reason", "")) or "kept"
    logger.info(f"Prescreen kept: {cand.title!r}", extra={"reason": reason})
    return True, reason
