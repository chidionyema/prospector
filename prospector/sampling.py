"""Verbalized Sampling directive (G4).

A model asked for "k ideas" returns k samples from the MODE of its distribution, which is
why batches converge on the same shapes (arXiv:2510.01171 — Verbalized Sampling). Verbalized
Sampling asks the model to report the distribution instead: each idea carries a self-
estimated typicality, and the batch must contain a stated minimum of low-typicality ideas.

The self-report is NEVER a filter — an atypical idea is not a better idea, it is only
further from the mode, and only the grounded moat may rule on quality. The number is
carried into tags so the diversity meter (prospector/diversity.py) can measure whether
this directive actually moved the batch.
"""
from __future__ import annotations

import math
from typing import Any

from .telemetry import logger


def typicality_directive(cfg: Any, k: int) -> str:
    """Return the Verbalized Sampling directive, or "" when the gate is off / on any error.

    `k` is the target candidate count for THIS run; the directive names the minimum count
    of low-typicality ideas the model must produce. min_atypical_fraction is bounded below
    by `max(1, ceil(k * frac))` — a fraction of 0.1 on k=5 still asks for at least 1 idea
    in the atypical tail, because a batch with zero atypical entries is observationally
    indistinguishable from a batch where the directive was ignored."""
    vcfg = (getattr(cfg, "generation", {}) or {}).get("verbalized_sampling", {}) or {}
    if not vcfg.get("enabled", False):
        return ""
    try:
        thr = float(vcfg.get("atypical_threshold", 0.3))
        frac = float(vcfg.get("min_atypical_fraction", 0.4))
        n_k = int(k)
        n_atypical = max(1, int(math.ceil(max(0, n_k) * frac))) if n_k > 0 else 1
        return (
            "VERBALIZED SAMPLING (report the distribution, not just its mode). With each idea also "
            "return a \"typicality\" field: a number from 0.0 to 1.0 estimating how likely a generic "
            "AI assistant given this same brief would produce that idea. 1.0 = the first thing anything "
            "would say. 0.0 = a mode almost nothing reaches. "
            f"At least {n_atypical} of the {k} ideas in this batch MUST have typicality <= {thr}, "
            "and you must actually REACH those modes rather than relabelling a typical idea with a "
            "low number. Being unusual is not a licence to be vague: an atypical idea still needs a "
            "specifically nameable payer, a real wedge, and the same commodity pre-mortem as every "
            "other idea here."
        )
    except (TypeError, ValueError) as e:
        # Everything between the gate check and the return is arithmetic over config values,
        # so a malformed `atypical_threshold` / `min_atypical_fraction` is the only failure
        # this can legitimately have; a broad `except Exception` here would swallow a
        # refactor's bug into the SAME "" the gate-off path returns. That matters more than
        # it looks: the directive is measured by the diversity meter, so an "" from a config
        # typo does not read as "the feature is broken", it reads as "verbalized sampling
        # was enabled and did not move the batch". ERROR, because the gate says ON.
        logger.error(f"verbalized_sampling is enabled but its directive could not be built "
                     f"(check listing generation.verbalized_sampling config); the batch will "
                     f"be generated WITHOUT it: {e}", exc_info=True)
        return ""


def typicality_score(val: Any) -> float | None:
    """Coerce a self-reported typicality value to a float in [0, 1], or None if unparseable.

    Mirrors `_automatability_score` (in `generate.py`) so the two self-reported fields behave
    identically — the diversity meter reads them the same way and a regression in one is a
    regression in both. Tolerates the schema being loosely specified: accepts a 0-1 float,
    a 0-100 number, a percentage string ("85%"), or a stringified float. None for missing
    / empty / unparseable so the caller decides policy.

    bool is NOT a valid typicality — return None for it (unlike automatability, a True/False
    typicality carries no meaning). isinstance(val, bool) is checked BEFORE the int/float
    branch because bool is a subclass of int in Python."""
    if val is None:
        return None
    if isinstance(val, bool):  # MUST come before int/float — bool is a subclass of int
        return None
    if isinstance(val, (int, float)):
        f = float(val)
        return max(0.0, min(1.0, f / 100.0 if f > 1.0 else f))
    s = str(val).strip()
    if not s:
        return None
    if s.endswith("%"):
        s = s[:-1].strip()
    try:
        f = float(s)
        return max(0.0, min(1.0, f / 100.0 if f > 1.0 else f))
    except ValueError:
        return None
