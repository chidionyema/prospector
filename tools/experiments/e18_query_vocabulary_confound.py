#!/usr/bin/env python3
"""E18 — does leading a query with OUR packaging vocabulary cost us retrieval?

THE FILED CLAIM
---------------
A measurement filed but deliberately not acted on: ~31% of shipped query bases lead
with the packaging vocabulary the generator uses to describe a business shape
("solo", "fixed-fee", "done-for-you", "productised") rather than with a domain term.
The worry is concrete and testable — a search engine given our shelf-label instead of
the buyer's word should retrieve less, and retrieve worse.

The naive check agrees, loudly and consistently: wrapper-leading checks retrieve
fewer sources and go `unverifiable` far more often, across every check. That is the
kind of result that gets acted on.

WHY THAT WOULD HAVE BEEN A MISTAKE
----------------------------------
The treatment is not assigned per query. It is assigned per CANDIDATE: an idea whose
title is "a solo, fixed-fee, done-for-you X" produces wrapper-leading queries on
nearly all of its checks, and an idea with a strong domain noun produces almost none.
So the two arms are not two ways of searching for the same thing — they are two
different populations of IDEA, and vocabulary is confounded with how hard the idea is
to ground in the first place. `[design]` below reports exactly how few candidates
contribute to both arms, which is what makes the between-candidate contrast
uninterpretable rather than merely noisy.

WHAT THIS MEASURES INSTEAD
--------------------------
A doubly-adjusted, within-candidate estimate:

  1. residualise each observation on its `check_name` (checks differ hugely in base
     retrievability, and the arms are not balanced across checks), then
  2. pair WITHIN each candidate, comparing that candidate's wrapper-leading checks to
     its own non-wrapper checks, so idea difficulty cancels.

Only candidates that appear in both arms can contribute, which is why the paired n is
small — that smallness is the finding, not a defect of the method.

THE BAR
-------
Change the query builder only if the adjusted interval excludes zero in the HARMFUL
direction. E1 is just-measured evidence in this same programme that blind query
surgery can be wrong-signed, so "the naive number was big" is not a licence to edit.

LIMITS (stated, not discovered later)
-------------------------------------
* Observational. Nobody randomised the vocabulary; adjustment is not randomisation,
  and an unmeasured driver of both vocabulary and groundability would still bias it.
* Wrapper detection is FIRST-TOKEN only, against a fixed list. It measures "leads
  with", not "contains".
* `sources` counts what was retrieved and kept, not what was useful.
* A null here is "no evidence at the effect size that motivated the change", not
  "proof of no effect" — the paired n bounds what is detectable.
"""
from __future__ import annotations

import argparse
import collections
import math
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _corpus as corpus  # noqa: E402  - sibling helper, path set above

NAME = "E18"

#: The generator's own packaging vocabulary — the words that describe the SHAPE of a
#: business rather than its domain. Leading a search with these is the behaviour under
#: test.
WRAPPER_WORDS = frozenset({
    "solo", "solo-operated", "fixed-fee", "fixed", "done-for-you", "done",
    "productized", "productised", "paid", "web", "vertical",
})


def describe() -> str:
    return ("E18 — tests whether packaging-vocabulary-leading queries retrieve worse, "
            "correcting for the fact that the vocabulary is a property of the CANDIDATE")


def leads_with_wrapper(query: str) -> bool:
    """True when the FIRST token is packaging vocabulary. Deliberately not
    'contains': a domain-led query that mentions 'fixed-fee' later is not the
    behaviour under test."""
    text = (query or "").strip().lower()
    if not text:
        return False
    return re.split(r"\s+", text)[0] in WRAPPER_WORDS


def load_observations() -> list[dict[str, Any]]:
    """One row per CHECK that actually issued queries. A check with no queries has no
    vocabulary and cannot be in either arm."""
    rows: list[dict[str, Any]] = []
    for path, dossier in corpus.iter_dossiers():
        cid = corpus.candidate_id(path, dossier)
        for chk in dossier.get("checks") or []:
            queries = chk.get("queries") or []
            if not queries:
                continue
            rows.append({
                "candidate_id": cid,
                "check": chk.get("check_name") or "(unnamed)",
                "wrapper": 1 if any(leads_with_wrapper(q) for q in queries) else 0,
                "n_sources": len(chk.get("sources") or []),
                "unverifiable": 1 if chk.get("verdict") == "unverifiable" else 0,
                "n_queries": len(queries),
            })
    return rows


def _mean(xs: list[float]) -> float | None:
    return (sum(xs) / len(xs)) if xs else None


def naive_contrast(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The between-candidate comparison — the one that looks decisive and is not."""
    arm = {0: [r for r in rows if not r["wrapper"]], 1: [r for r in rows if r["wrapper"]]}
    out = {}
    for label, key in (("mean_sources", "n_sources"), ("unverifiable_rate", "unverifiable")):
        out[label] = {
            "wrapper": _mean([r[key] for r in arm[1]]),
            "domain": _mean([r[key] for r in arm[0]]),
        }
    out["n_wrapper"] = len(arm[1])
    out["n_domain"] = len(arm[0])
    out["wrapper_prevalence"] = (len(arm[1]) / len(rows)) if rows else None
    return out


def design_diagnostic(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """How many candidates contribute to BOTH arms. Near zero means the treatment is a
    property of the candidate and the naive contrast compares populations of idea."""
    arms: dict[str, set[int]] = collections.defaultdict(set)
    for r in rows:
        arms[r["candidate_id"]].add(r["wrapper"])
    both = sum(1 for s in arms.values() if len(s) > 1)
    return {
        "n_candidates": len(arms),
        "candidates_in_both_arms": both,
        "share_in_both_arms": (both / len(arms)) if arms else None,
        "interpretation": (
            "the paired estimate can only use candidates in BOTH arms; a small share "
            "means the vocabulary travels with the idea, so the between-candidate "
            "contrast confounds vocabulary with idea difficulty"),
    }


def paired_adjusted(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Residualise on check_name, then difference within candidate."""
    by_check_src: dict[str, list[float]] = collections.defaultdict(list)
    by_check_unv: dict[str, list[float]] = collections.defaultdict(list)
    for r in rows:
        by_check_src[r["check"]].append(r["n_sources"])
        by_check_unv[r["check"]].append(r["unverifiable"])
    mu_src = {k: sum(v) / len(v) for k, v in by_check_src.items()}
    mu_unv = {k: sum(v) / len(v) for k, v in by_check_unv.items()}

    per: dict[str, dict[int, list[tuple[float, float]]]] = collections.defaultdict(
        lambda: {0: [], 1: []})
    for r in rows:
        per[r["candidate_id"]][r["wrapper"]].append(
            (r["n_sources"] - mu_src[r["check"]], r["unverifiable"] - mu_unv[r["check"]]))

    d_src: list[float] = []
    d_unv: list[float] = []
    for groups in per.values():
        if not groups[0] or not groups[1]:
            continue
        d_src.append(_mean([x[0] for x in groups[1]]) - _mean([x[0] for x in groups[0]]))
        d_unv.append(_mean([x[1] for x in groups[1]]) - _mean([x[1] for x in groups[0]]))

    def summarise(xs: list[float]) -> dict[str, Any]:
        n = len(xs)
        if n < 2:
            # One pair cannot produce a variance. Reporting a CI here would invent
            # precision that does not exist.
            return {"n": n, "mean": _mean(xs), "se": None, "t": None,
                    "ci95": None, "note": "fewer than 2 pairs; no interval is estimable"}
        m = sum(xs) / n
        var = sum((x - m) ** 2 for x in xs) / (n - 1)
        se = math.sqrt(var / n)
        return {"n": n, "mean": m, "se": se,
                "t": (m / se) if se else None,
                "ci95": [m - 1.96 * se, m + 1.96 * se] if se else None}

    return {"d_sources": summarise(d_src), "d_unverifiable": summarise(d_unv)}


def verdict(adjusted: dict[str, Any]) -> tuple[str, str]:
    """Act only on an interval that excludes zero in the HARMFUL direction.

    Harm means: FEWER sources (d_sources upper bound < 0) or MORE unverifiable
    (d_unverifiable lower bound > 0).
    """
    src, unv = adjusted["d_sources"], adjusted["d_unverifiable"]
    if not src.get("ci95") or not unv.get("ci95"):
        return "INSUFFICIENT", "too few paired candidates to estimate an interval"
    harm_src = src["ci95"][1] < 0
    harm_unv = unv["ci95"][0] > 0
    if harm_src or harm_unv:
        return "ACT", ("adjusted interval excludes zero in the harmful direction: "
                       + ("fewer sources; " if harm_src else "")
                       + ("more unverifiable" if harm_unv else ""))
    return "DO_NOT_ACT", (
        "the naive association does not survive adjustment — the adjusted intervals "
        "span zero, and the point estimates do not even carry the naive sign. Editing "
        "the query builder on the naive number would be a blind change of unknown sign.")


def run(args: list[str]) -> dict[str, Any]:
    ap = argparse.ArgumentParser(prog=NAME)
    ap.add_argument("--all", action="store_true",
                    help="accepted for symmetry with the other harnesses; E18 always "
                         "uses the whole corpus (it has no sampling step)")
    ap.parse_args(args)

    rows = load_observations()
    naive = naive_contrast(rows)
    design = design_diagnostic(rows)
    adjusted = paired_adjusted(rows)
    call, why = verdict(adjusted)

    print(f"{NAME} — packaging-vocabulary queries over {len(rows)} checks "
          f"({design['n_candidates']} candidates)")
    prev = naive["wrapper_prevalence"]
    print(f"  prevalence: {prev * 100:.1f}% of checks lead with packaging vocabulary"
          if prev is not None else "  prevalence: n/a")
    print(f"  [naive, between-candidate] mean_sources "
          f"{naive['mean_sources']['wrapper']:.2f} (wrapper) vs "
          f"{naive['mean_sources']['domain']:.2f} (domain); unverifiable "
          f"{naive['unverifiable_rate']['wrapper'] * 100:.2f}% vs "
          f"{naive['unverifiable_rate']['domain'] * 100:.2f}%")
    print(f"  [design] only {design['candidates_in_both_arms']}/{design['n_candidates']} "
          f"({(design['share_in_both_arms'] or 0) * 100:.1f}%) candidates appear in BOTH arms "
          f"-> the naive contrast compares IDEAS, not queries")
    for label, key in (("d_sources", "d_sources"), ("d_unverifiable", "d_unverifiable")):
        s = adjusted[key]
        ci = (f"[{s['ci95'][0]:+.4f}, {s['ci95'][1]:+.4f}]" if s.get("ci95") else "n/a")
        print(f"  [adjusted] {label}: n={s['n']} mean={s['mean']:+.4f} 95%CI={ci}")
    print(f"  VERDICT: {call} — {why}")

    return {
        "headline": {"verdict": call, "why": why,
                     "wrapper_prevalence": naive["wrapper_prevalence"],
                     "n_checks": len(rows)},
        "naive_between_candidate": naive,
        "design": design,
        "adjusted_paired": adjusted,
        "wrapper_words": sorted(WRAPPER_WORDS),
        "corpus_fingerprint": corpus.corpus_fingerprint(),
        "limits": [
            "Observational: vocabulary was never randomised, so adjustment is not randomisation.",
            "Wrapper detection is FIRST-TOKEN only, against a fixed list — 'leads with', not 'contains'.",
            "n_sources counts what was retrieved and kept, not what was useful.",
            "A null is 'no evidence at the motivating effect size', bounded by the paired n.",
        ],
    }


if __name__ == "__main__":
    run(sys.argv[1:])
