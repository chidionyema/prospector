#!/usr/bin/env python3
"""Shared pair construction for the HHEM audits (E15, E17). Read-only over store/.

One decision is worth stating because both experiments rest on it.

WHAT IS THE HYPOTHESIS? The check's `rationale` — the sentence the moat wrote to justify its
verdict. Not the verdict word, and not the candidate's claim. HHEM asks "is this text supported by
that text", so the only thing it can audit is a text the model produced. `rationale` is exactly
the artefact §11 gap 2 calls rationale infidelity: the stated reason may not be what the cited
passage says, and nothing in the pipeline has ever checked.

WHAT IS THE PREMISE? Each CITED passage, scored SEPARATELY, taking the max. Not the concatenation.
HHEM is a 512-token cross-encoder: concatenating six passages truncates all but the first one or
two, so a concatenated premise would score a rationale as ungrounded because of a tokenizer limit
and the finding would be an artefact of framing. Max-over-passages asks the question that matches
the check's own semantics — "is the rationale supported by at least one passage it cited" — and is
immune to passage ORDER.

TWO CONTROLS, because a scorer that returns low everywhere would produce a spectacular and
meaningless infidelity rate:
  NULL     — the same rationale against a passage belonging to a DIFFERENT candidate, chosen by a
             deterministic offset (no RNG, so the control reproduces byte-for-byte). This is the
             false-positive floor and is what the decision threshold is calibrated on.
  UNCITED  — the same rationale against a passage the check RETRIEVED but did NOT cite. The
             in-between case: same topic, not the evidence the model claimed to use.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _corpus import candidate_id, iter_dossiers, source_index  # noqa: E402

MAX_PREMISE_CHARS = 1500     # ~375 tokens; under HHEM's 512-token window with the hypothesis
MAX_PASSAGES = 3             # per check, in stored order
RULED = {"supported", "refuted"}


def collect_checks(verdicts: set[str] | None = None,
                   moat_only: bool = False,
                   moat: set[str] | None = None) -> list[dict]:
    """Every check with a rationale, annotated with its cited and uncited passages.

    Returns records in a deterministic order (dossier path, then check index), so any sampling
    downstream is reproducible without an RNG.
    """
    moat = moat or {"claude_cli", "claude", "claude-cli/default"}
    out: list[dict] = []
    for path, dossier in iter_dossiers():
        index = source_index(dossier)
        cid = candidate_id(path, dossier)
        for pos, chk in enumerate(dossier.get("checks") or []):
            verdict = chk.get("verdict")
            if verdicts is not None and verdict not in verdicts:
                continue
            if moat_only and (chk.get("provider") or "") not in moat:
                continue
            rationale = (chk.get("rationale") or "").strip()
            if not rationale:
                continue
            cite_ids = [str(c) for c in (chk.get("citations") or [])]
            cited, dangling = [], []
            for c in cite_ids:
                src = index.get(c)
                if src and (src.get("text") or "").strip():
                    cited.append(src)
                else:
                    dangling.append(c)
            own = [s for s in (chk.get("sources") or [])
                   if isinstance(s, dict) and (s.get("text") or "").strip()]
            uncited = [s for s in own if str(s.get("source_id")) not in set(cite_ids)]
            out.append({
                "path": Path(path).name,
                "candidate_id": cid,
                "pos": pos,
                "check_name": chk.get("check_name") or "?",
                "verdict": verdict,
                "confidence": chk.get("confidence"),
                "provider": chk.get("provider"),
                "retrieval_failed": bool(chk.get("retrieval_failed")),
                "degraded": bool(chk.get("degraded")),
                "rationale": rationale,
                "cited": cited,
                "uncited": uncited,
                "n_citations": len(cite_ids),
                "n_dangling": len(dangling),
                "gate_fired": dossier.get("gate_fired"),
            })
    return out


def clip(text: str) -> str:
    return (text or "").strip()[:MAX_PREMISE_CHARS]


def stratified_sample(records: list[dict], key: str, limit: int | None) -> list[dict]:
    """Systematic sample that preserves the class mix of `key`. Deterministic: no RNG.

    Within each class the records keep their collection order and every k-th is taken, so the
    sample spans the whole corpus timeline rather than the first N dossiers on disk — which
    matters here, because provider era and prompt version both change over that timeline.
    """
    if limit is None or limit >= len(records) or limit <= 0:
        return list(records)
    by_class: dict[str, list[dict]] = {}
    for rec in records:
        by_class.setdefault(str(rec.get(key)), []).append(rec)
    out: list[dict] = []
    for cls in sorted(by_class):
        group = by_class[cls]
        want = max(1, round(limit * len(group) / len(records)))
        want = min(want, len(group))
        step = len(group) / want
        out.extend(group[min(len(group) - 1, int(i * step))] for i in range(want))
    return out


def build_pairs(records: list[dict], control: bool = True,
                max_passages: int = MAX_PASSAGES,
                uncited_arm: bool = True, uncited_max: int = 1
                ) -> tuple[list[tuple[str, str]], list[dict]]:
    """(pairs, plan). `plan` records which pair indices belong to which record and arm.

    HHEM costs ~1.6 s per pair on this box (measured 2026-08-07, 12 torch threads), so which arms
    are built is a real budget decision and not a detail. E17 does not read the UNCITED arm at
    all, and building it there would have doubled that experiment's runtime to produce numbers
    nothing consumes — hence the switch rather than a fixed set of arms.
    """
    pairs: list[tuple[str, str]] = []
    plan: list[dict] = []
    n = len(records)
    for i, rec in enumerate(records):
        entry = {"i": i, "cited": [], "uncited": [], "null": []}
        for src in rec["cited"][:max_passages]:
            entry["cited"].append(len(pairs))
            pairs.append((clip(src.get("text")), rec["rationale"]))
        for src in (rec["uncited"][:uncited_max] if uncited_arm else []):
            entry["uncited"].append(len(pairs))
            pairs.append((clip(src.get("text")), rec["rationale"]))
        if control and n > 1:
            # Deterministic offset: half the list away, so the borrowed passage is from a
            # different candidate and the choice reproduces exactly on a re-run.
            donor = records[(i + n // 2) % n]
            pool = (donor["cited"] or donor["uncited"])[:1]
            for src in pool:
                if donor["candidate_id"] != rec["candidate_id"]:
                    entry["null"].append(len(pairs))
                    pairs.append((clip(src.get("text")), rec["rationale"]))
        plan.append(entry)
    return pairs, plan


def maxscore(idxs: list[int], scores: list[float]) -> float | None:
    vals = [scores[i] for i in idxs if i < len(scores)]
    return max(vals) if vals else None


def quantile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    return sorted_vals[min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))]
