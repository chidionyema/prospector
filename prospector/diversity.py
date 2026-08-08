"""Per-batch diversity meter (G1). Distinct-k per NoveltyBench: the number of
functionally distinct ideas in a batch, computed by greedy clustering on
content-token Jaccard (same signal dedup uses). Receipts are appended to
<store_dir>/generation_metrics.jsonl; this module must NEVER raise into the
generation path.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .dedup import _content_tokens
from .telemetry import logger

#: Env override for where generation-side artifacts land. Production leaves it unset
#: and gets `cfg.store_dir`; `tests/conftest.py` sets it autouse.
#:
#: This exists because a test does not have to touch a store to write to the production
#: one: `tests/unit/test_blue_sky.py` builds a real Config via `load_config()` — whose
#: `store_dir` IS the repo's `store/` — and hands it a stub store, so the first version
#: of this module created `store/exhausted_families.json` on every pytest run. Same
#: shape as the audit-log / durable-ledger / prescreen-shadow leaks before it, and the
#: same fix: resolve the path per call through an env var the suite can redirect.
ARTIFACT_DIR_ENV = "PROSPECTOR_GENERATION_ARTIFACT_DIR"


def generation_artifact_dir(cfg: Any) -> Path:
    """Directory for generation-side artifacts: the env override, else cfg.store_dir.

    Resolved per call (never bound at import) so `monkeypatch.setenv` takes effect for
    a test that imported the module earlier.
    """
    override = os.environ.get(ARTIFACT_DIR_ENV, "").strip()
    return Path(override) if override else Path(cfg.store_dir)


def _jaccard(a: frozenset, b: frozenset) -> float:
    """Jaccard similarity of two token sets (0.0..1.0).

    Returns 0.0 when the union is empty so a caller never has to guard against
    a 0/0 — the empty-batch edge case is the caller's job to skip, not ours.
    """
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def distinct_k(candidates: list[Any], token_threshold: float = 0.34) -> int:
    """Greedy distinct-k cluster on content-token Jaccard.

    Each candidate is compared against the SEED of every existing cluster (the
    first member's token set). It joins the FIRST cluster whose seed has
    Jaccard >= token_threshold — same signal dedup.py uses for the "reworded
    same idea" axis. Candidates that join nothing become a new cluster (their
    tokens become the seed). Order is preserved: iteration follows the input
    list, so the result is deterministic for a deterministic input.
    """
    seeds: list[frozenset] = []
    for c in candidates:
        title = getattr(c, "title", "") or ""
        one_liner = getattr(c, "one_liner", "") or ""
        tokens = _content_tokens(f"{title} {one_liner}")
        if not tokens:
            # Empty token sets would always score 0.0 by Jaccard and become a
            # phantom cluster of one; skip the candidate entirely — it carries
            # no signal and no comparison is meaningful.
            continue
        joined = False
        for seed in seeds:
            if _jaccard(tokens, seed) >= token_threshold:
                joined = True
                break
        if not joined:
            seeds.append(tokens)
    return len(seeds)


def _entropy(hist: dict[str, int]) -> float:
    """Shannon entropy of a histogram, normalised to 0.0..1.0 by log2(n).

    A single bucket (or zero buckets) carries no information, so entropy is 0.0
    in both cases — distinct from a uniform 1-bucket distribution which would
    technically be log2(1)=0 anyway. The log2(1)==0 division is guarded.
    """
    if not hist:
        return 0.0
    total = sum(hist.values())
    if total <= 0:
        return 0.0
    n_keys = len(hist)
    if n_keys <= 1:
        return 0.0
    h = 0.0
    for c in hist.values():
        if c <= 0:
            continue
        p = c / total
        h -= p * math.log2(p)
    return h / math.log2(n_keys)


def batch_report(candidates: list[Any], token_threshold: float = 0.34,
                 atypical_threshold: float = 0.3) -> dict:
    """Summarise a batch: distinct-k + pairwise overlap + per-axis histograms.

    Axes (structural_form / audience / market / ambition_tier) are extracted
    with defensive defaults so a Candidate-shaped object missing any field still
    produces a valid report. Empty-string and "unknown" both normalise to a
    single bucket so a generator that leaves an axis blank does not appear more
    diverse than it actually is.
    """
    n = len(candidates)

    def _axis(c: Any, attr: str, tags_key: str | None = None) -> str:
        if tags_key:
            tags = getattr(c, "tags", {}) or {}
            if not isinstance(tags, dict):
                return ""
            v = tags.get(tags_key, "")
        else:
            v = getattr(c, attr, "")
        return (str(v or "").strip().lower()) or "unknown"

    axes: dict[str, dict[str, Any]] = {}
    for axis, attr, tags_key in (
        ("structural_form", "structural_form", None),
        ("audience", "", "audience"),
        ("market", "market", None),
        ("ambition_tier", "ambition_tier", None),
    ):
        hist: dict[str, int] = {}
        for c in candidates:
            key = _axis(c, attr, tags_key)
            hist[key] = hist.get(key, 0) + 1
        axes[axis] = {"histogram": hist, "entropy": _entropy(hist)}

    # Pairwise Jaccard over the candidate fingerprint (title + one_liner).
    fps = [_content_tokens(f"{getattr(c, 'title', '') or ''} "
                           f"{getattr(c, 'one_liner', '') or ''}")
           for c in candidates]
    overlaps: list[float] = []
    for i in range(n):
        for j in range(i + 1, n):
            # Skip the empty-token edge case — two empty sets jaccard to 0.0
            # which would otherwise inflate the "distinct" signal.
            if not fps[i] or not fps[j]:
                continue
            overlaps.append(_jaccard(fps[i], fps[j]))
    if overlaps:
        mean_overlap = sum(overlaps) / len(overlaps)
        max_overlap = max(overlaps)
    else:
        mean_overlap = 0.0
        max_overlap = 0.0

    dk = distinct_k(candidates, token_threshold)

    # G4 observability: did the Verbalized Sampling directive actually reach lower-probability
    # modes, or did the model just relabel its usual output? `n_reported` is the honest
    # denominator — when the directive is off, or the model ignored it, it is 0 and the other
    # two figures are 0.0 rather than a mean over nothing.
    tvals: list[float] = []
    for c in candidates:
        tags = getattr(c, "tags", {}) or {}
        if not isinstance(tags, dict):
            continue
        v = tags.get("typicality")
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        tvals.append(float(v))
    typicality = {
        "n_reported": len(tvals),
        "mean": (sum(tvals) / len(tvals)) if tvals else 0.0,
        "atypical_fraction": (
            sum(1 for v in tvals if v <= atypical_threshold) / len(tvals)) if tvals else 0.0,
    }

    return {
        "n": n,
        "distinct_k": dk,
        "distinct_ratio": (dk / n) if n else 0.0,
        "mean_pairwise_overlap": mean_overlap,
        "max_pairwise_overlap": max_overlap,
        "typicality": typicality,
        "axes": axes,
    }


def write_receipt(
    cfg: Any,
    stage: str,
    candidates: list[Any],
    token_threshold: float = 0.34,
) -> dict | None:
    """Append one batch_report row to <store_dir>/generation_metrics.jsonl.

    Gated by `generation.diversity_meter` (default off — opt-in so existing
    runs are byte-identical when the flag is absent). The whole body runs
    inside a broad except: if the disk write fails, the JSON serialisation
    fails, or anything else goes wrong, we log a warning and return None
    rather than ever break the generation path.
    """
    gen_cfg = getattr(cfg, "generation", {}) or {}
    if not gen_cfg.get("diversity_meter", False):
        return None
    try:
        vcfg = gen_cfg.get("verbalized_sampling", {}) or {}
        atypical_threshold = float(vcfg.get("atypical_threshold", 0.3))
        report = batch_report(candidates, token_threshold, atypical_threshold)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            **report,
        }
        path = generation_artifact_dir(cfg) / "generation_metrics.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        logger.info(
            f"diversity[{stage}]: n={report['n']} distinct_k={report['distinct_k']} "
            f"mean_overlap={report['mean_pairwise_overlap']:.2f}"
        )
        return record
    except Exception as e:
        logger.warning(f"diversity meter failed, skipping: {e}")
        return None
