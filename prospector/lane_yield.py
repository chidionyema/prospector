"""Measured lane quotas (G9): reallocate generation effort by realised value per lane.

`config.yaml lane_quota` is a hand-tuned constant — 3/5/4/3 across side_hustle/smb/growth/
venture, last edited by a human reading a table. This module derives the same four numbers
from the store instead, so the split tracks what the lanes actually produce rather than what
someone believed a month ago.

READ THIS BEFORE ENABLING IT — the tension is real and is not hidden here.
The founder rule is "improve the IDEAS, never the pass rate; kill stats are a report card,
not a lever" (memory: feedback-generation-quality-not-kill-rate). This module points a lever
at exactly that report card, so three things constrain it:

  1. It changes only WHERE generation effort is spent. It touches no gate, no threshold, no
     confidence floor and no publish decision. Nothing here can make a weak idea survive;
     the moat is bit-for-bit as hard whichever lane a candidate came from.
  2. It weights on realised VALUE, not on pass COUNT: expected composite per ruled
     candidate. A lane that passes often with mediocre composites does not out-rank a lane
     that passes rarely with excellent ones. Optimising the pass count alone is the failure
     mode the rule exists to prevent, so the estimator deliberately cannot express it.
  3. `exploration_reserve` (default 0.2) is uniform and unconditional, and every lane keeps
     a floor of 1. Venture currently has 0 PASS in 35 (`config.yaml:310-314`); a pure
     value-weighting would starve it to nothing and the catalogue would quietly collapse
     onto whichever lane was ahead the day this was switched on. A lane that is never
     generated into can never produce the evidence that would revive it, which makes an
     unreserved version self-confirming rather than measured.

The estimator is a shrinkage mean: a lane's own expected value is blended toward the global
one in proportion to how little evidence it has, so a lane with 6 ruled rows barely moves off
the global number and a lane with 600 essentially uses its own. That is what stops one lucky
early PASS from capturing the whole batch.

DEFAULT OFF (`generation.lane_quota_mode: static`). Read-only, zero-LLM, and it fails open to
None on any error, so a missing DB, an old schema or a corrupt row means the static quota.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Optional

from .telemetry import logger

# Pseudo-rows of prior. A lane needs evidence on this order before its own number dominates
# the global one. 20 is roughly one batch-week at the current cadence: long enough that a
# single fluke PASS cannot swing the split, short enough that a genuinely fertile lane is
# recognised within a few days rather than a quarter.
_PRIOR_STRENGTH = 20.0

_DEFAULT_RESERVE = 0.2


def _db_path(cfg: Any) -> Path:
    return Path(getattr(cfg, "store_dir", ".")) / "prospector.db"


def _lane_value(cfg: Any, lanes: list[str]) -> Optional[dict[str, float]]:
    """Expected composite per RULED candidate, per lane, shrunk toward the global mean.

    Returns None when the store cannot answer — no DB, no `ambition_tier` column, or no
    ruled rows at all — so the caller falls back to the static quota rather than inventing
    a split from nothing.

    The denominator is `pass + kill`. Deferred and provisional rows are excluded on both
    sides: a DEFER is an unfinished verdict, and counting one as a zero-value outcome would
    let a moat outage rewrite the generation budget. That is the same error class as the
    2026-08-06 dossier that rendered seven failed verdict calls as a reasoned KILL.
    """
    db = _db_path(cfg)
    if not db.exists():
        return None
    conn = sqlite3.connect(str(db), timeout=10.0)
    try:
        have = {r[1] for r in conn.execute("PRAGMA table_info(dossiers)")}
        if not {"ambition_tier", "decision", "composite"} <= have:
            return None
        # provisional may be absent on a very old index; treat it as 0 in that case.
        prov = "COALESCE(provisional, 0)" if "provisional" in have else "0"
        rows = conn.execute(
            f"SELECT ambition_tier AS lane, decision, composite FROM dossiers "
            f"WHERE {prov} = 0 AND decision IN ('pass', 'kill')"
        ).fetchall()
    finally:
        conn.close()

    ruled: dict[str, int] = {}
    value: dict[str, float] = {}
    for lane, decision, composite in rows:
        key = str(lane or "").strip().lower()
        if not key:
            continue
        ruled[key] = ruled.get(key, 0) + 1
        if str(decision).strip().lower() == "pass":
            c = composite if isinstance(composite, (int, float)) and not isinstance(
                composite, bool) else 0.0
            value[key] = value.get(key, 0.0) + float(c)

    total_ruled = sum(ruled.values())
    if not total_ruled:
        return None
    global_ev = sum(value.values()) / total_ruled

    # A global_ev of exactly 0 means the store has ruled rows but not one PASS with a
    # composite. There is no value signal to allocate on, so say so instead of dividing by
    # zero or handing every lane an identical share dressed up as a measurement.
    if global_ev <= 0.0:
        return None

    out: dict[str, float] = {}
    for lane in lanes:
        n = ruled.get(lane, 0)
        v = value.get(lane, 0.0)
        # Shrinkage: (own evidence + prior evidence) / (own weight + prior weight).
        out[lane] = (v + _PRIOR_STRENGTH * global_ev) / (n + _PRIOR_STRENGTH)
    return out


def _apportion(weights: dict[str, float], total: int, lanes: list[str]) -> dict[str, int]:
    """Largest-remainder apportionment of `total` across `lanes`, floor 1 each.

    Largest-remainder rather than round-then-nudge: rounding each share independently does
    not sum to `total`, and the nudge loop that fixes it hands the correction to whichever
    lane happens to sort first. Largest-remainder gives the leftover seats to the lanes with
    the largest fractional claim, which is both deterministic and defensible.
    """
    floors = {t: 1 for t in lanes}
    spare = total - len(lanes)
    if spare <= 0:
        return floors
    tw = sum(weights.get(t, 0.0) for t in lanes)
    if tw <= 0:
        return floors
    exact = {t: spare * weights.get(t, 0.0) / tw for t in lanes}
    counts = {t: int(exact[t]) for t in lanes}
    left = spare - sum(counts.values())
    for t in sorted(lanes, key=lambda x: (exact[x] - int(exact[x]), weights.get(x, 0.0)),
                    reverse=True)[:max(0, left)]:
        counts[t] += 1
    return {t: floors[t] + counts[t] for t in lanes}


def measured_lane_quota(cfg: Any, lanes: list[str],
                        static_total: int) -> Optional[dict[str, int]]:
    """Return a measured per-lane quota summing to `static_total`, or None to fall back.

    `static_total` is passed in rather than recomputed so the measured split is a pure
    REALLOCATION of the operator's declared batch size. Changing the mode must not change
    how many candidates a run generates — only which lanes they land in — or the cost of a
    tick would move as a side effect of a quality experiment, and the two would be
    impossible to tell apart in the ledger.
    """
    try:
        if not lanes or static_total < len(lanes):
            return None
        value = _lane_value(cfg, lanes)
        if not value:
            return None
        gen = getattr(cfg, "generation", {}) or {}
        reserve = float(gen.get("lane_exploration_reserve", _DEFAULT_RESERVE))
        reserve = max(0.0, min(1.0, reserve))

        tv = sum(value.values())
        if tv <= 0:
            return None
        n = len(lanes)
        weights = {t: reserve / n + (1.0 - reserve) * value[t] / tv for t in lanes}
        quota = _apportion(weights, static_total, lanes)
        logger.info(
            "lane_quota_mode=measured", extra={
                "lanes": lanes, "value": {k: round(v, 4) for k, v in value.items()},
                "reserve": reserve, "quota": quota, "total": static_total})
        return quota
    except Exception as e:
        logger.warning(f"measured lane quota failed, falling back to static: {e}")
        return None
