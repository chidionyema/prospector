#!/usr/bin/env python3
"""E6B — can the lexical prefilter remove verify work without losing a PASS?

WHY THIS EXISTS (read before quoting any number out of it)
----------------------------------------------------------
E6 as specced measures *agreement with the LLM prescreen* and has been "blocked on
live daemon ticks" since 2026-08-07. Two facts on disk say that block is the wrong
shape:

1.  The shadow log holds 15 usable rows, 13 with `llm_called`, and **zero** LLM
    rejects. Agreement cannot be estimated from it at any sample size soon.
2.  The bar is *"≥20% call reduction at no PASS loss"* — and that is NOT the same
    statistic as agreement. The LLM prescreen itself drops only 48/990 = 4.85% of
    candidates (`store/scheduler/batch_diagnostics.jsonl`, funnel `prescreen_in` vs
    `prescreened_out`), so a prefilter that merely *agrees* with it can never save
    20% of calls. To clear the bar the prefilter must drop candidates the LLM
    would have KEPT, and the only thing that makes that safe is that they were
    never going to PASS. Only 4.4% of candidates ever do.

So the bar is a question about **eventual outcome**, not about agreement, and the
eventual outcome is already on disk for 1,789 indexed candidates. E6B answers the
bar directly, offline, today. It does not answer E6-as-specced, and it is not a
substitute for it: it replaces the proxy with the thing the proxy stood for.

DESIGN
------
*   Label = `decision == 'pass'` from the dossier index, NOT `llm_keep`. This is
    the load-bearing change and the reason a naive corpus replay is degenerate:
    every dossier on disk belongs to a candidate that already *survived* prescreen,
    so an `llm_keep`-labelled exemplar corpus is 100% keep, scores identically 1.0,
    and drops nothing. The bug would look like "the prefilter is perfectly safe".
*   Out-of-sample by construction, exactly as production is: score against the
    exemplars seen so far, THEN learn the row. Replay is in `created_at` order.
*   The scorer is the shipped `PrescreenShadow.score()`, driven directly. A
    reimplementation here could pass its own tests while diverging from production.
*   Scores do not depend on the threshold (the exemplar list grows regardless of
    the drop decision), so scores are computed ONCE and the threshold is swept
    over the resulting array. Sweeping the replay would be the same numbers at
    N times the cost.

KNOWN LIMITS (stated, not buried)
---------------------------------
*   **Population bias.** The corpus contains only candidates that survived the LLM
    prescreen; the 4.85% it drops have no dossier. The prefilter in production sees
    that 4.85% too. The replay therefore measures the drop rate over a slightly
    *easier* population than production, and the true achievable rate is likely a
    little higher than reported here. It is a floor, not a ceiling.
*   **`defer` is unruled.** A deferred candidate may still become a PASS on re-vet.
    Dropping one is not yet a PASS loss but it is not proven safe either, so
    defers dropped are reported separately and the headline "safe" rate is the one
    that loses neither a pass NOR a defer. The looser rate is reported beside it.
*   This is a retrospective replay on one corpus. It bounds what the prefilter
    *would* have done; it is not a live A/B.

Run:  .venv/bin/python tools/experiments/runner.py run E6B [--limit N] [--bar 0.20]
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import _corpus as corpus  # noqa: E402  - sibling helper, path set above

from prospector.prescreen_prefilter import (  # noqa: E402
    PrefilterSettings,
    PrescreenShadow,
    load_embedder,
)

NAME = "E6B"
DOC_REF = "docs/COMMERCIAL_READINESS_PROGRAM.md §3 (row E6), §22, §32"

#: The bar E6 was set at: fraction of prescreen calls the prefilter must remove.
DEFAULT_BAR = 0.20

#: Deliberately NOT a fixed grid. The score is a similarity-weighted PASS-rate over
#: neighbours, and only ~4.4% of candidates ever pass, so scores pile up at or near
#: 0.0. On a 0.02-step grid the first rung already drops ~90% of the corpus and the
#: grid resolution, not the data, decides the answer. Sweeping the OBSERVED scores
#: enumerates every drop set the threshold rule can actually produce, exactly.
def candidate_thresholds(scored: list[dict[str, Any]]) -> list[float]:
    """Every threshold that yields a distinct drop set, and no others.

    `would_drop` is `score < threshold`, so a threshold equal to an observed score
    drops everything strictly below it. Enumerating the observed scores therefore
    enumerates the achievable drop sets; the extra top rung drops all of them.
    """
    vals = sorted({r["score"] for r in scored if r["score"] is not None})
    if not vals:
        return []
    return vals + [vals[-1] + 1e-9]


def describe() -> str:
    return ("E6B — replays the shipped lexical prefilter over the dossier corpus "
            "labelled by FINAL outcome, and reports the largest share of prescreen "
            "calls it could have removed while losing no PASS.")


# --------------------------------------------------------------------------- #
# corpus
# --------------------------------------------------------------------------- #

def load_rows(limit: Optional[int] = None) -> list[tuple[str, str, str, str]]:
    """(candidate_id, text, decision, created_at) in replay order.

    Ordered by `created_at` so the replay is causal: a candidate is only ever
    scored against candidates that preceded it. Ties broken on candidate_id so
    the run is deterministic and the fingerprint means something.
    """
    rows = corpus.db_query(
        "select candidate_id, coalesce(title,''), coalesce(one_liner,''), "
        "coalesce(decision,''), coalesce(created_at,'') from dossiers "
        "where decision is not null and decision != '' "
        "order by created_at asc, candidate_id asc"
    )
    out: list[tuple[str, str, str, str]] = []
    for cid, title, one_liner, decision, created in rows:
        text = f"{title} {one_liner}".strip()
        if not text:
            continue
        out.append((str(cid), text, str(decision).lower(), str(created)))
    if limit:
        out = out[:limit]
    return out


# --------------------------------------------------------------------------- #
# replay
# --------------------------------------------------------------------------- #

def replay(rows: list[tuple[str, str, str, str]],
           settings: PrefilterSettings) -> list[dict[str, Any]]:
    """Score every row against only its predecessors, then learn it.

    Returns one dict per row carrying the score (None => the prefilter abstained,
    which in production means it never drops).
    """
    embedder = load_embedder(settings.backend)
    scored: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as td:
        # A real PrescreenShadow so the shipped scorer is what runs. The log path
        # is a throwaway: `_seeded` is forced True so a PRODUCTION shadow log can
        # never leak exemplars into a replay and make it look better than it is.
        shadow = PrescreenShadow(Path(td) / "replay.jsonl",
                                 settings=settings, embedder=embedder)
        shadow._seeded = True
        shadow._exemplars = []
        for cid, text, decision, created in rows:
            score, n_used, abstain = shadow.score(text)
            scored.append({
                "candidate_id": cid, "decision": decision, "created_at": created,
                "score": score, "neighbours_used": n_used, "abstain_reason": abstain,
            })
            vec = embedder.encode(text)
            if vec:
                shadow._exemplars.append((vec, decision == "pass"))
                if len(shadow._exemplars) > settings.max_exemplars:
                    shadow._exemplars = shadow._exemplars[-settings.max_exemplars:]
    return scored


def sweep(scored: list[dict[str, Any]],
          thresholds: list[float] | None = None) -> list[dict[str, Any]]:
    """Drop-rate and PASS/defer loss at each threshold. Mirrors `would_drop`.

    With no thresholds given the sweep is exact over the observed scores, so the
    reported safe rate is a property of the data rather than of a grid.
    """
    if thresholds is None:
        thresholds = candidate_thresholds(scored)
    n = len(scored)
    n_pass = sum(1 for r in scored if r["decision"] == "pass")
    out = []
    for t in thresholds:
        dropped = [r for r in scored if r["score"] is not None and r["score"] < t]
        pass_dropped = sum(1 for r in dropped if r["decision"] == "pass")
        defer_dropped = sum(1 for r in dropped if r["decision"] == "defer")
        out.append({
            "threshold": t,
            "n_dropped": len(dropped),
            "drop_rate": (len(dropped) / n) if n else 0.0,
            "pass_dropped": pass_dropped,
            "defer_dropped": defer_dropped,
            "pass_loss_rate": (pass_dropped / n_pass) if n_pass else 0.0,
        })
    return out


def best_safe(curve: list[dict[str, Any]], *, allow_defer_loss: bool) -> dict[str, Any] | None:
    """Highest drop rate that loses no PASS (and optionally no defer).

    Returns None when NOTHING is safe at any swept threshold — which is a real
    answer, not a zero. A caller that reads a missing row as 0.0 would report
    "safe but useless" for a prefilter that is actually unsafe everywhere.
    """
    safe = [c for c in curve
            if c["pass_dropped"] == 0 and (allow_defer_loss or c["defer_dropped"] == 0)]
    if not safe:
        return None
    return max(safe, key=lambda c: c["drop_rate"])


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #

def run(args: list[str]) -> dict[str, Any]:
    ap = argparse.ArgumentParser(prog="E6B")
    ap.add_argument("--limit", type=int, default=None,
                    help="replay only the first N candidates (smoke runs)")
    ap.add_argument("--bar", type=float, default=DEFAULT_BAR,
                    help="call-reduction bar to judge against (default 0.20)")
    ap.add_argument("--threshold", type=float, default=None,
                    help="also report the shipped operating point (config threshold)")
    ns = ap.parse_args(args)

    settings = PrefilterSettings()
    rows = load_rows(ns.limit)
    if not rows:
        return {"error": "no dossier rows with a decision; nothing to replay"}

    scored = replay(rows, settings)
    curve = sweep(scored)
    strict = best_safe(curve, allow_defer_loss=False)
    loose = best_safe(curve, allow_defer_loss=True)

    n = len(scored)
    n_abstained = sum(1 for r in scored if r["score"] is None)
    n_pass = sum(1 for r in scored if r["decision"] == "pass")

    strict_rate = strict["drop_rate"] if strict else None
    verdict = "INCONCLUSIVE"
    if strict_rate is not None:
        verdict = "MEETS_BAR" if strict_rate >= ns.bar else "FAILS_BAR"
    elif loose is None:
        verdict = "FAILS_BAR"  # nothing is safe anywhere on the sweep

    print(f"E6B — prefilter pass-safety replay over {n} candidates "
          f"({n_pass} PASS, {n_abstained} abstained)")
    print(f"  bar: remove >= {ns.bar*100:.0f}% of prescreen calls, losing no PASS")
    if strict:
        print(f"  SAFE (no pass, no defer lost): drop_rate={strict['drop_rate']*100:.2f}% "
              f"at threshold {strict['threshold']}")
    else:
        print("  SAFE (no pass, no defer lost): NOTHING is safe at any swept threshold")
    if loose:
        print(f"  SAFE (no pass lost, defers allowed): drop_rate={loose['drop_rate']*100:.2f}% "
              f"at threshold {loose['threshold']} ({loose['defer_dropped']} defers dropped)")
    print(f"  VERDICT: {verdict}")

    return {
        "headline": (f"prefilter can safely remove "
                     f"{(strict_rate or 0.0)*100:.2f}% of prescreen calls "
                     f"vs a {ns.bar*100:.0f}% bar -> {verdict}"),
        "verdict": verdict,
        "bar": ns.bar,
        "n_candidates": n,
        "n_pass": n_pass,
        "n_abstained": n_abstained,
        "safe_no_pass_no_defer": strict,
        "safe_no_pass": loose,
        "curve": curve,
        "settings": {
            "backend": settings.backend, "neighbours": settings.neighbours,
            "min_similarity": settings.min_similarity,
            "min_exemplars": settings.min_exemplars,
            "max_exemplars": settings.max_exemplars,
        },
        "corpus_fingerprint": corpus.corpus_fingerprint(),
        "limits": [
            "Label is FINAL decision, not llm_keep: an llm_keep-labelled replay is "
            "degenerate because every dossier already survived prescreen.",
            "Population excludes the 4.85% the LLM prescreen drops (they have no "
            "dossier), so the reported safe rate is a floor, not a ceiling.",
            "defer is unruled; the headline rate loses neither a pass nor a defer.",
            "Retrospective replay on one corpus, not a live A/B.",
        ],
    }


if __name__ == "__main__":  # pragma: no cover - exercised via runner.py
    import json as _json
    print(_json.dumps(run(sys.argv[1:]), indent=2, default=str))
