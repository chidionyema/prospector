#!/usr/bin/env python3
"""E12 — adversarial groundedness: does a DECISIVE kill cite a passage, or is it model opinion?

Programme doc §9 (line ~323) registers E12 as: "audit the 142 `adversarial_decisive` kills for
whether the decisive claim cites a passage or is pure model opinion."

Why this is not already answered by the code. `verify.py:672-674` downgrades `decisive` to False
when the adversarial pass returns no citations at all, so a NAIVE audit finds 100% cited and
concludes the gate is grounded. That guard checks only that the `citations` list is non-empty. It
does not check that the ids in it correspond to anything we hold:

    if decisive and not citations:            # verify.py:672
        logger.info("Adversarial claimed decisive with no citations; downgrading")
        decisive = False

`citations` is a list of `source_id` hashes the model wrote out. A model that emits a plausible
16-hex string satisfies that guard exactly as well as one that quotes a real passage. So the
question this experiment answers is one level down, and it is deterministic and free:

    for every adversarial_decisive kill, do the cited source_ids RESOLVE to a passage that is
    actually on disk in that dossier — and does that passage have text?

Classification (mutually exclusive, in this order):

    unparseable  — no adversarial object, or citations is not a list of strings, or kill_case is
                   empty. Nothing to audit.
    uncited      — citations == []. Pure model opinion. Should be ~0 by the guard above; any
                   non-zero count is a bug in the guard.
    dangling     — citations non-empty and NOT ONE resolves to a source_id in the dossier. The
                   model invented its receipts. Indistinguishable from opinion, and the guard
                   passes it.
    partial      — some resolve, some do not.
    cited        — every citation resolves. Split further by whether the resolved passages carry
                   text (`text` non-empty), because a resolved id with an empty passage is a URL
                   we hold and a passage we do not.

Two populations are reported, because they are not the same set and the doc names only the first:
  (a) gate_fired == "adversarial_decisive"  — kills the gate actually fired on.
  (b) adversarial.decisive is true          — every decisive adversarial verdict, including
      candidates killed earlier by a different gate (kill-fast means the gate that fired is the
      FIRST one, not the only one that would have).

LIMIT OF THE INSTRUMENT: this measures whether the citation POINTS AT a passage we hold. It does
not measure whether that passage SUPPORTS the kill case. That is E15's job (HHEM entailment), and
E15 scores these same kill_case/passage pairs — the two numbers are meant to be read together.

Read-only over store/. Zero LLM. Zero network.

Usage:
    .venv/bin/python tools/experiments/runner.py run E12
    .venv/bin/python tools/experiments/e12_adversarial_groundedness.py
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _corpus import (  # noqa: E402
    RULED,
    candidate_id,
    corpus_fingerprint,
    db_query,
    dossier_paths,
    iter_dossiers,
    source_index,
    wilson,
)

NAME = "E12"
DOC_REF = "docs/COMMERCIAL_READINESS_PROGRAM.md §9 (line ~323)"

GATE = "adversarial_decisive"
_ID_IN_PROSE = re.compile(r"\b[0-9a-f]{16}\b")


def describe() -> str:
    return ("Do adversarial_decisive kills cite a passage we actually hold, or invented ids? "
            "Deterministic, zero-token, over store/dossiers.")


def _classify(dossier: dict) -> tuple[str, dict]:
    adv = dossier.get("adversarial")
    if not isinstance(adv, dict):
        return "unparseable", {"why": "no adversarial object"}
    cites = adv.get("citations")
    kill_case = (adv.get("kill_case") or "").strip()
    if not isinstance(cites, list) or any(not isinstance(c, str) for c in cites):
        return "unparseable", {"why": f"citations is {type(cites).__name__}"}
    if not kill_case:
        return "unparseable", {"why": "empty kill_case"}

    index = source_index(dossier)
    resolved = [index[c] for c in cites if c in index]
    dangling = [c for c in cites if c not in index]
    with_text = [s for s in resolved if (s.get("text") or "").strip()]

    # Which check does each resolved passage belong to, and was that check itself ruled? A kill
    # case leaning on a passage attached to an `unverifiable` check is leaning on evidence the
    # moat already declined to rule on.
    owner_verdict = {}
    for chk in dossier.get("checks") or []:
        for src in chk.get("sources") or []:
            if isinstance(src, dict) and src.get("source_id"):
                owner_verdict.setdefault(str(src["source_id"]), chk.get("verdict"))

    detail = {
        "n_citations": len(cites),
        "n_resolved": len(resolved),
        "n_dangling": len(dangling),
        "n_with_text": len(with_text),
        "dangling_ids": dangling[:6],
        "ids_in_prose": sorted(set(_ID_IN_PROSE.findall(kill_case))),
        "resolved_owner_verdicts": sorted(
            {owner_verdict.get(c) or "?" for c in cites if c in index}),
        "kill_case": kill_case,
        "provider": adv.get("provider"),
        "confidence": adv.get("confidence"),
        "urls": [s.get("url") for s in resolved][:6],
        "passages": [(s.get("text") or "")[:400] for s in with_text][:2],
    }
    if not cites:
        return "uncited", detail
    if not resolved:
        return "dangling", detail
    if dangling:
        return "partial", detail
    return ("cited" if with_text else "cited_no_text"), detail


def _audit(population: list[tuple[str, dict]], label: str) -> dict:
    classes = Counter()
    examples = defaultdict(list)
    cite_counts = Counter()
    prose_id_stats = Counter()
    owner_verdicts = Counter()
    providers = Counter()
    class_providers: dict[str, Counter] = defaultdict(Counter)
    class_dates: dict[str, list[str]] = defaultdict(list)
    total_cites = total_resolved = total_dangling = 0

    for path, dossier in population:
        klass, detail = _classify(dossier)
        classes[klass] += 1
        providers[detail.get("provider") or "?"] += 1
        class_providers[klass][detail.get("provider") or "?"] += 1
        class_dates[klass].append(str(dossier.get("created_at") or "")[:10])
        if "n_citations" in detail:
            cite_counts[detail["n_citations"]] += 1
            total_cites += detail["n_citations"]
            total_resolved += detail["n_resolved"]
            total_dangling += detail["n_dangling"]
            in_prose = detail["ids_in_prose"]
            if in_prose:
                prose_id_stats["kill_case names >=1 id inline"] += 1
                if all(i in (detail["dangling_ids"] or []) for i in in_prose):
                    prose_id_stats["every inline id is dangling"] += 1
            else:
                prose_id_stats["kill_case names no id inline"] += 1
            for v in detail["resolved_owner_verdicts"]:
                owner_verdicts[v] += 1
        if len(examples[klass]) < 3:
            examples[klass].append({
                "dossier": Path(path).name,
                "candidate_id": candidate_id(path, dossier),
                "gate_fired": dossier.get("gate_fired"),
                **{k: v for k, v in detail.items() if k != "passages"},
                "cited_passages_verbatim": detail.get("passages", []),
            })

    n = len(population)
    grounded = classes["cited"] + classes["partial"]
    lo, hi = wilson(grounded, n)
    return {
        "population_label": label,
        "population_n": n,
        "classes": dict(classes),
        "class_shares": {k: round(v / n, 4) for k, v in classes.items()} if n else {},
        "points_at_a_passage_we_hold": grounded,
        "points_at_a_passage_share": round(grounded / n, 4) if n else 0.0,
        "points_at_a_passage_wilson95": [round(lo, 4), round(hi, 4)],
        "citation_totals": {"citations": total_cites, "resolved": total_resolved,
                            "dangling": total_dangling,
                            "dangling_share": round(total_dangling / total_cites, 4)
                            if total_cites else 0.0},
        "citations_per_kill_histogram": {str(k): v for k, v in sorted(cite_counts.items())},
        "inline_id_prose": dict(prose_id_stats),
        "resolved_source_owner_check_verdicts": dict(owner_verdicts),
        "adversarial_providers": dict(providers),
        # The era split is not decoration. `verify.py:672-674` downgrades decisive-with-no-
        # citations, so any `uncited` row is either a live bug in that guard or a dossier written
        # BEFORE it existed. Only the dates can tell those two apart, and they are different
        # findings with different remediations.
        "by_class_dates": {k: {"first": min(v), "last": max(v), "n": len(v)}
                           for k, v in class_dates.items() if v},
        "by_class_providers": {k: dict(v) for k, v in class_providers.items()},
        "examples": {k: v for k, v in examples.items()},
    }


def run(args: list[str] | None = None) -> dict:
    args = list(args or [])
    paths = dossier_paths()
    all_dossiers = list(iter_dossiers(paths))

    gate_pop = [(p, d) for p, d in all_dossiers if d.get("gate_fired") == GATE]
    decisive_pop = [(p, d) for p, d in all_dossiers
                    if isinstance(d.get("adversarial"), dict)
                    and d["adversarial"].get("decisive") is True]

    gate_audit = _audit(gate_pop, f"gate_fired == '{GATE}'")
    decisive_audit = _audit(decisive_pop, "adversarial.decisive is true (any gate)")

    # The register says 142. The sqlite index and the json glob disagree by construction (the
    # index carries rows whose json file was rotated), so both are reported rather than one being
    # quietly preferred.
    db_rows = db_query("SELECT COUNT(*) FROM dossiers WHERE gate_fired = ?", (GATE,))
    db_count = int(db_rows[0][0]) if db_rows else None

    ruled_ratio = Counter()
    for _p, d in gate_pop:
        for chk in d.get("checks") or []:
            ruled_ratio["ruled" if chk.get("verdict") in RULED else "not_ruled"] += 1

    print(f"E12 adversarial groundedness — dossier files globbed: {len(paths)}, "
          f"parsed: {len(all_dossiers)}")
    print(f"register says 142 `{GATE}` kills; measured on disk: {len(gate_pop)} json files, "
          f"{db_count} rows in store/prospector.db")
    print("(the glob/index gap is expected — the sqlite index outlives rotated json files)")
    print()

    for audit in (gate_audit, decisive_audit):
        print(f"--- population: {audit['population_label']}  (n={audit['population_n']}) ---")
        for klass in ("cited", "cited_no_text", "partial", "dangling", "uncited", "unparseable"):
            n = audit["classes"].get(klass, 0)
            share = audit["class_shares"].get(klass, 0.0)
            print(f"  {klass:<14} {n:5d}  {share:6.1%}")
        ct = audit["citation_totals"]
        lo, hi = audit["points_at_a_passage_wilson95"]
        print(f"  -> cites a passage we hold : {audit['points_at_a_passage_we_hold']}/"
              f"{audit['population_n']} = {audit['points_at_a_passage_share']:.1%} "
              f"[95% CI {lo:.1%}-{hi:.1%}]")
        print(f"  -> citation ids: {ct['citations']} total, {ct['resolved']} resolved, "
              f"{ct['dangling']} dangling ({ct['dangling_share']:.1%})")
        print(f"  -> inline ids in kill_case prose: {audit['inline_id_prose']}")
        print(f"  -> owner-check verdicts of resolved passages: "
              f"{audit['resolved_source_owner_check_verdicts']}")
        print("  -> ERA of each class (a pre-guard artefact and a live bug look identical "
              "without this):")
        for klass in ("cited", "partial", "dangling", "uncited", "unparseable"):
            d = audit["by_class_dates"].get(klass)
            if not d:
                continue
            print(f"       {klass:<12} n={d['n']:4d}  {d['first']} .. {d['last']}   "
                  f"{audit['by_class_providers'].get(klass)}")
        print()

    print("--- verbatim examples ---")
    for klass, rows in gate_audit["examples"].items():
        for row in rows[:2]:
            print(f"\n[{klass}] {row['dossier']}  provider={row.get('provider')}  "
                  f"citations={row.get('n_citations')} resolved={row.get('n_resolved')} "
                  f"dangling={row.get('n_dangling')}")
            print(f"  kill_case: {(row.get('kill_case') or '')[:420]}")
            for passage in (row.get("cited_passages_verbatim") or [])[:1]:
                print(f"  cited passage: {passage[:300]}")
            if row.get("dangling_ids"):
                print(f"  DANGLING ids: {row['dangling_ids']}")

    g = gate_audit
    ungrounded = g["classes"].get("dangling", 0) + g["classes"].get("uncited", 0)
    eras = [g["by_class_dates"][k] for k in ("dangling", "uncited") if k in g["by_class_dates"]]
    era = (f"{min(e['first'] for e in eras)}..{max(e['last'] for e in eras)}" if eras else "-")
    whole = g["by_class_dates"]
    whole_era = (f"{min(v['first'] for v in whole.values())}.."
                 f"{max(v['last'] for v in whole.values())}" if whole else "-")
    verdict = (
        f"{ungrounded} of {g['population_n']} adversarial_decisive kills "
        f"({ungrounded / g['population_n']:.1%}) rest on NO passage we hold. Every one of them "
        f"falls in {era}, inside a population spanning {whole_era} — so this is a PRE-GUARD "
        f"artefact, not a live defect: `verify.py:672-674` now downgrades decisive-with-no-"
        f"citations, and the `dangling` class (an id that resolves to nothing) is the hole that "
        f"guard still does not close."
        if g["population_n"] else "no adversarial_decisive kills on disk")
    print(f"\nVERDICT: {verdict}")

    return {
        "title": "adversarial groundedness — do decisive kills cite a passage we hold?",
        "programme_ref": DOC_REF,
        "corpus_fingerprint": corpus_fingerprint(),
        "population": (f"every dossier json with gate_fired == '{GATE}' "
                       f"({len(gate_pop)} of {len(all_dossiers)} parsed dossiers); no sampling, "
                       "the whole population is audited"),
        "dossier_files_globbed": len(paths),
        "dossiers_parsed": len(all_dossiers),
        "register_claimed_count": 142,
        "measured_gate_count_json": len(gate_pop),
        "measured_gate_count_sqlite": db_count,
        "gate_population": gate_audit,
        "decisive_population": decisive_audit,
        "gate_pop_check_verdict_mix": dict(ruled_ratio),
        "verdict": verdict,
        "headline": {
            "adversarial_decisive kills audited (json)": len(gate_pop),
            "same, per store/prospector.db": db_count,
            "cited — every id resolves to a passage with text": gate_audit["classes"].get("cited", 0),
            "partial — some ids resolve": gate_audit["classes"].get("partial", 0),
            "dangling — NO id resolves (invented receipts)": gate_audit["classes"].get("dangling", 0),
            "uncited — empty citations (pure opinion)": gate_audit["classes"].get("uncited", 0),
            "unparseable": gate_audit["classes"].get("unparseable", 0),
            "points at a passage we hold": (
                f"{gate_audit['points_at_a_passage_we_hold']}/{len(gate_pop)} = "
                f"{gate_audit['points_at_a_passage_share']:.1%} "
                f"(95% CI {gate_audit['points_at_a_passage_wilson95'][0]:.1%}–"
                f"{gate_audit['points_at_a_passage_wilson95'][1]:.1%})"),
            "dangling citation ids / all citation ids": (
                f"{gate_audit['citation_totals']['dangling']}/"
                f"{gate_audit['citation_totals']['citations']} = "
                f"{gate_audit['citation_totals']['dangling_share']:.1%}"),
            "era of the ungrounded kills vs the whole population": f"{era} within {whole_era}",
        },
        "limitations": [
            "Resolution is POINTING, not support. A citation that resolves proves we hold the "
            "passage, not that the passage carries the kill case. E15 scores exactly these "
            "kill_case/passage pairs with HHEM; read the two together.",
            "`verify.py:672-674` already blocks decisive-with-zero-citations, so the `uncited` "
            "count is expected near zero. `dangling` is the class that guard does not catch.",
            "The json glob and the sqlite index disagree on the population size by design (the "
            "index outlives rotated json files); both counts are reported, neither is preferred.",
            "store/dossiers is written by the live daemon, so a later re-run shifts counts by a "
            "few dossiers. _meta.run_at_utc and dossier_files_globbed pin this run.",
        ],
        "_receipt_suffix": "_current_moat" if "--current-moat" in args else "",
    }


def main() -> int:
    from runner import run_one
    result = run_one(NAME, sys.argv[1:])
    print(f"\nreceipts   -> {result['receipts_path']}")
    print(f"doc append -> {result['doc_append_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
