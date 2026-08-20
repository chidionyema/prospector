#!/usr/bin/env python3
"""Phase 1.2 — build a human-labelled ground-truth set, blind.

    python3 tools/build_label_set.py --store <store> --n 200 --out docs/labels/

Why this is the keystone. Five of our eight axes are readable today; the two that decide whether
the engine is any GOOD are not. A4 discrimination is saturated at 1.00 on nine items, so it can
register neither an improvement nor a regression. A8 reports 26.71% attempted, and percent
attempted can be driven to 100 by a model that guesses, so on its own it is meaningless. Both
need the same missing thing: cases where somebody who is not the engine has said what the right
answer was.

**The set is BLIND by construction, and that is the whole methodology.** Two files come out of
here. The labelling file carries the claim and the passages and nothing else. The answer key
carries the engine's verdict, keyed by pair id, and the labeller never opens it. If the labeller
can see what the engine said, agreement stops being evidence — a human who sees `unverifiable`
agrees with `unverifiable` far more often than one who does not, and the number we would compute
is anchoring, not accuracy.

**The strata come from E-105, not from convenience.** A uniform sample over failures would spend
95% of a scarce human budget on one population and answer a question we can already answer. The
three strata each decide something different:

  ruled                     — precision on what we DO rule. Is `supported` actually supported?
  unverifiable_with_passage — the 9,784. THE question: correct abstention, or over-abstention?
  unverifiable_no_evidence  — the 481. The E-105 prefilter's population; confirms it is safe.

Sampling is deterministic on `--seed` against a frozen corpus, so the same command reproduces the
same set and two runs are comparable rather than merely similar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.experiments import _corpus  # noqa: E402
from tools.experiments.e105_unverifiable_prefilter import classify  # noqa: E402

CATCHABLE = ("no_source_retrieved", "sources_carry_no_text", "zero_overlap")

# A neutral question per check, phrased so that `supported`, `refuted` and `unverifiable` are all
# natural answers. The engine's own rationale must NEVER be shown to the labeller: it is the
# verdict written out in prose ("the passages say nothing about X"), so a labeller who reads it
# has been told the answer. Ten names appear in the corpus, not the six in CLAUDE.md — four are
# legacy and still need a question or their pairs are unlabellable.
CHECK_QUESTIONS = {
    "pain_reality": "Do the passages show this problem is real and that the named buyer has it?",
    "value_durability": "Do the passages show this value would persist rather than evaporate?",
    "incumbency": "Do the passages show whether someone already solves this for this buyer?",
    "payer_solvency": "Do the passages show the named payer can afford to pay for this?",
    "distribution": "Do the passages show a reachable channel to these buyers?",
    "legality": "Do the passages show whether this is lawful, or what regulates it?",
    "buyer_intent": "Do the passages show these buyers actively seeking or paying for a fix?",
    "currency": "Do the passages show this is current rather than already resolved or obsolete?",
    "route_to_market": "Do the passages show a concrete route to reach these buyers?",
    "claims_verifiable": "Do the passages substantiate the specific factual claims made?",
}
DEFAULT_QUESTION = "Do the passages settle this check for this candidate?"

# Deliberately not equal thirds. The middle stratum is where the open question lives.
STRATA = {
    "ruled": 0.25,
    "unverifiable_with_passage": 0.60,
    "unverifiable_no_evidence": 0.15,
}

LABEL_INSTRUCTIONS = """\
For each pair below, read ONLY the claim and the passages, then choose one label:

  supported     — the passages state the claim, or state something that entails it.
  refuted       — the passages state something that contradicts the claim.
  unverifiable  — the passages do not settle it either way.

Two rules that decide most of the hard cases:

1. Rule on the PASSAGES ALONE. Not on what you know to be true. If the claim is obviously true
   in the world but the passages do not say so, the answer is `unverifiable`. This is the same
   rule the engine is meant to follow, so grading it on any other rule measures nothing.
2. `unverifiable` is a real answer, not a way of skipping a hard one. Use it whenever the
   passages are merely ABOUT the subject without settling the claim.

Write your label into the `human_label` field. Add a one-line `note` when the case was hard —
those notes are how the rubric gets fixed.
"""


class BlindnessViolation(RuntimeError):
    """The task file was about to tell the labeller what the engine said."""


# The task row's key set is CLOSED. Anything not on this list does not reach the labeller.
# An allow-list rather than a deny-list, because the leak arrives as a NEW field somebody adds
# for a good reason, and a deny-list only ever knows about yesterday's leaks.
ALLOWED_TASK_KEYS = frozenset(
    {
        "pair_id",
        "check_name",
        "question",
        "candidate_title",
        "candidate_one_liner",
        "candidate_hypothesis",
        "candidate_who_pays",
        "queries",
        "passages",
        "human_label",
        "note",
        "labeller",
        "labelled_at",
    }
)

# Engine jargon: a word that does not occur in ordinary prose, so its presence in a field we
# construct means engine output leaked. `supported` and `refuted` are deliberately NOT here —
# both are everyday English. The guard's first two real runs flagged a retrieved passage reading
# "88 per cent of freelancers do not feel supported by the UK government", and then a candidate's
# own hypothesis. Both were correct rows. A word-list cannot separate our verdict from English,
# which is why the key allow-list above is the real guard and this is only a backstop.
ENGINE_JARGON = ("unverifiable",)


def assert_blind(task_row: dict) -> None:
    """Refuse to write a task row that leaks the answer. Called on EVERY row, every run.

    This exists because the leak it catches is invisible in the output. The first version of
    this tool shipped `claim` = the engine's rationale, which reads as a normal, well-formed
    field full of sensible prose — and is the verdict written out longhand ("the passages say
    nothing about X"). It also shipped a visible `stratum`, and two of the three stratum names
    contain the word "unverifiable". Nothing was malformed. No test failed. No error printed.
    It was found by one person reading one row by hand, which is not a mechanism.

    A blindness bug does not corrupt the file, it corrupts the NUMBER computed from it months
    later, and by then the labels are spent and the anchoring is unrecoverable. So the check
    runs at write time and raises, rather than warning.
    """
    extra = set(task_row) - ALLOWED_TASK_KEYS
    if extra:
        raise BlindnessViolation(
            f"task row {task_row.get('pair_id')} carries unapproved field(s) {sorted(extra)!r}. "
            "If it is engine output it must go to the answer key; if it is genuinely safe for "
            "the labeller, add it to ALLOWED_TASK_KEYS deliberately."
        )
    # `passages` is retrieved web text shown verbatim — it is the evidence, and it may say
    # anything at all. Only the fields we write are scanned.
    constructed = {k: v for k, v in task_row.items() if k != "passages"}
    blob = json.dumps(constructed).lower()
    for word in ENGINE_JARGON:
        if word in blob:
            raise BlindnessViolation(
                f"task row {task_row.get('pair_id')} contains engine jargon {word!r} in a field "
                "we construct; the labeller must not be able to infer the engine's verdict"
            )


def _pair_id(dossier_path: Path | str, check_index: int) -> str:
    # _corpus.iter_dossiers yields a str on some paths and a Path on others; coerce rather than
    # trusting either, because a bare str silently loses .name and kills the whole run.
    raw = f"{Path(dossier_path).name}:{check_index}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def collect(store: Path) -> dict[str, list[dict]]:
    """One pass over the corpus, bucketed into the three strata."""
    buckets: dict[str, list[dict]] = {k: [] for k in STRATA}

    for path, dossier in _corpus.iter_dossiers():
        if not isinstance(dossier, dict) or "checks" not in dossier:
            continue
        index = _corpus.source_index(dossier)
        candidate = dossier.get("candidate") or {}
        title = str(candidate.get("title") or candidate.get("name") or "")

        for i, check in enumerate(dossier.get("checks") or []):
            if not isinstance(check, dict):
                continue
            verdict = str(check.get("verdict") or "")
            sources, _missing = _corpus.cited_sources(check, index)
            passages = [str(s.get("text") or "") for s in sources if s.get("text")]

            if verdict in ("supported", "refuted"):
                stratum = "ruled"
            elif verdict == "unverifiable":
                stratum = (
                    "unverifiable_no_evidence"
                    if classify(check, index) in CATCHABLE
                    else "unverifiable_with_passage"
                )
            else:
                continue

            # A pair with no passage at all is unlabellable by a human under rule 1 — there is
            # nothing to read. Those stay counted in E-105 and out of the human budget.
            if not passages and stratum != "unverifiable_no_evidence":
                continue

            check_name = str(check.get("check_name") or "")
            buckets[stratum].append(
                {
                    "pair_id": _pair_id(path, i),
                    "check_name": check_name,
                    "question": CHECK_QUESTIONS.get(check_name, DEFAULT_QUESTION),
                    "candidate_title": title,
                    "candidate_one_liner": str(candidate.get("one_liner") or "")[:600],
                    "candidate_hypothesis": str(candidate.get("hypothesis") or "")[:1200],
                    "candidate_who_pays": str(candidate.get("who_pays") or "")[:400],
                    "queries": [str(q) for q in (check.get("queries") or [])],
                    "passages": [p[:4000] for p in passages[:6]],
                    "_engine_verdict": verdict,
                    "_engine_rationale": str(check.get("rationale") or "")[:2000],
                    "_engine_confidence": check.get("confidence"),
                    "_provider": str(check.get("provider") or ""),
                    "_source": Path(path).name,
                    "_stratum": stratum,
                }
            )
    return buckets


def sample(buckets: dict[str, list[dict]], n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    out: list[dict] = []
    for stratum, share in STRATA.items():
        pool = sorted(buckets[stratum], key=lambda r: r["pair_id"])  # deterministic order first
        want = round(n * share)
        if len(pool) <= want:
            picked = pool
        else:
            picked = rng.sample(pool, want)
        for row in picked:
            # Underscore-prefixed, so the writer below routes it to the ANSWER KEY. Two of the
            # three stratum names contain the word "unverifiable"; showing them to the labeller
            # leaks the engine's verdict on 75% of the set.
            row["_stratum"] = stratum
        out.extend(picked)
    return sorted(out, key=lambda r: r["pair_id"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--store", required=True)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20260820)
    ap.add_argument("--out", default="docs/labels")
    args = ap.parse_args(argv)

    store = Path(args.store).expanduser().resolve()
    os.environ.setdefault("PROSPECTOR_CORPUS_DIR", str(store / "dossiers"))

    buckets = collect(store)
    rows = sample(buckets, args.n, args.seed)
    fingerprint = _corpus.corpus_fingerprint()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = fingerprint.get("sha256", "unknown")[:8]

    task_path = out_dir / f"label-task-{stamp}.jsonl"
    key_path = out_dir / f"label-key-{stamp}.jsonl"
    readme_path = out_dir / f"label-README-{stamp}.md"

    with task_path.open("w", encoding="utf-8") as tf, key_path.open("w", encoding="utf-8") as kf:
        for row in rows:
            key = {k: row[k] for k in row if k.startswith("_")}
            key["pair_id"] = row["pair_id"]
            kf.write(json.dumps(key, sort_keys=True) + "\n")

            task = {k: v for k, v in row.items() if not k.startswith("_")}
            assert_blind(task)
            task["human_label"] = ""
            task["note"] = ""
            task["labeller"] = ""
            task["labelled_at"] = ""
            tf.write(json.dumps(task, sort_keys=True) + "\n")

    available = {k: len(v) for k, v in buckets.items()}
    got: dict[str, int] = {}
    for row in rows:
        got[row["_stratum"]] = got.get(row["_stratum"], 0) + 1

    readme_path.write_text(
        f"# Labelling task {stamp}\n\n"
        f"Corpus fingerprint `{fingerprint.get('sha256')}`, frozen={fingerprint.get('frozen')}, "
        f"{fingerprint.get('n_dossiers')} dossiers.\n"
        f"Seed {args.seed}. Requested {args.n}, produced {len(rows)}.\n\n"
        f"- Task file (open this one): `{task_path.name}`\n"
        f"- Answer key (DO NOT OPEN until every label is written): `{key_path.name}`\n\n"
        f"Strata produced: {json.dumps(got, sort_keys=True)}\n\n"
        f"Strata available in the corpus: {json.dumps(available, sort_keys=True)}\n\n"
        "## How to label\n\n" + LABEL_INSTRUCTIONS,
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "corpus": fingerprint,
                "seed": args.seed,
                "requested": args.n,
                "produced": len(rows),
                "strata_produced": got,
                "strata_available": available,
                "task_file": str(task_path),
                "key_file": str(key_path),
                "readme": str(readme_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
