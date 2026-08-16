"""Read the measured human target, and say which measures a document sits outside.

WHAT REPLACED WHAT. `register_lint` used to carry two numbers nobody measured: a sentence
may run to 25 words, and it may carry two commas. They came from `prompts/style/voice.md`
and their authority was that someone typed them. The measurement in
`docs/PROSE_CORPUS_PROGRAM.md` compared 766 of our documents against 270 human ombudsman
decisions in the same genre and found the 25-word rule STRICTER than professional English:
a human exceeds it in 31% of sentences, the human 95th percentile is 52%, and our own rate
is 52% — at the top of the human range but inside it. That rule was flagging normal writing.

The numbers now come from `data/prose_target.json`, which is committed, versioned and
carries the fingerprint of the corpora that produced it.

THE FOUR PRODUCTION FENCES, and where each one is kept:

  1. The target is a COMMITTED artifact. `TARGET_PATH` below, in the repo, in git.
  2. Lint time does NO network I/O and reads NO corpus. This module opens one JSON file and
     caches it. Nothing here fetches, and the corpora are gitignored and never shipped.
  3. The target carries the corpus fingerprint — document counts, word counts, tokeniser
     version — so any number traces back to the measurement that produced it. A target
     measured under a different tokeniser is REFUSED rather than read (`load_target`).
  4. Enforcement arms PER MEASURE. `armed` is written per measure by
     `tools.corpus.structure`, and this module will not report an unarmed one. Six are armed
     as of 2026-08-16; the sentence-length rate is deliberately not one of them.

WHAT THIS MODULE DOES NOT DO. It does not decide severity and it does not block. It answers
"is this document outside the human interval on an armed measure", and `register_lint`
decides what to say. Whether anything blocks is a config actuator, defaulted off, as with
every other rate in that file.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from prospector.prose_measure import TOKENISER_VERSION, document_measures

TARGET_PATH = Path(__file__).resolve().parent / "data" / "prose_target.json"

_CACHE: Dict[str, Dict[str, Any]] = {}


class TargetUnreadable(RuntimeError):
    """The shipped target is missing, malformed, or measured by a different tokeniser.

    Raised rather than swallowed: a linter that silently grades against nothing reports a
    clean pack for the same reason a broken one does, which is the failure this whole
    programme exists to stop.
    """


def load_target(path: Optional[Path] = None) -> Dict[str, Any]:
    """The committed target, cached per path. Reads one local file and nothing else."""
    p = Path(path) if path else TARGET_PATH
    key = str(p)
    if key in _CACHE:
        return _CACHE[key]
    try:
        raw = json.loads(p.read_text())
    except OSError as exc:
        raise TargetUnreadable(f"prose target not readable at {p}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise TargetUnreadable(f"prose target at {p} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("measures"), dict):
        raise TargetUnreadable(f"prose target at {p} has no measures block")
    got = str(raw.get("tokeniser_version"))
    if got != TOKENISER_VERSION:
        raise TargetUnreadable(
            f"prose target at {p} was measured with tokeniser version {got}, this build "
            f"counts with version {TOKENISER_VERSION}. Re-measure with "
            f"`python -m tools.corpus.structure --write-target {p}` — reading it as-is would "
            f"compare two tokenisers and call the difference a style defect.")
    _CACHE[key] = raw
    return raw


def armed_measures(path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Only the measures enforcement is armed on. An unarmed measure is still measured and
    still written into the receipt; it just cannot produce a finding."""
    return {k: v for k, v in load_target(path)["measures"].items() if v.get("armed")}


def grade(measures: Mapping[str, float], path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """One entry per ARMED measure this document sits outside the human interval on.

    The interval is the human 5th-95th percentile, so roughly one human document in ten
    falls outside on any single measure. That is why an individual finding is a warning and
    the decision to block is a rate actuator, exactly as `register_rate` already works.
    """
    out: List[Dict[str, Any]] = []
    for name, spec in armed_measures(path).items():
        if name not in measures:
            continue
        value = float(measures[name])
        lo, hi = float(spec["p5"]), float(spec["p95"])
        side = "above" if value > hi else ("below" if value < lo else None)
        if side is None:
            continue
        sd = float(spec.get("human_sd") or 0.0)
        out.append({
            "measure": name,
            "value": round(value, 3),
            "p5": lo,
            "p95": hi,
            "human_mean": spec.get("human_mean"),
            "side": side,
            "z": round((value - float(spec["human_mean"])) / sd, 2) if sd else None,
        })
    out.sort(key=lambda e: -abs(e.get("z") or 0.0))
    return out


def grade_text(text: str, path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Convenience: measure a document and grade it in one call. The measuring is
    `prose_measure.document_measures`, the same function that built the target."""
    return grade(document_measures(text), path)


#: What to tell a writer for each armed measure, PER SIDE. The measure name is a column
#: header; this is the sentence a person can act on.
#:
#: Both sides carry advice because the interval has two edges and a document can fall off
#: either. Which side WE fall off is in the target (`side`), and today it is "above" on the
#: punctuation measures and MATTR, "below" on hedges — but a single pack is not the corpus,
#: and telling a writer to split sentences when the document has almost no commas would be
#: advice pointing the wrong way.
#:
#: Keyed by measure so an unarmed measure carries no advice it is not entitled to give;
#: `test_prose_target` pins the two sets equal.
ADVICE = {
    "punct_hyphen_per_1k": {
        "above": "compound stacking — 'Front-Door Key-Safe Re-Siting'. Write the words out.",
        "below": "no hyphens at all, where a human writes the occasional compound.",
    },
    "punct_comma_per_1k": {
        "above": "commas. Split the sentence rather than adding a third clause to it.",
        "below": "almost no commas. A human holds a qualification inside the sentence; "
                 "prose with none reads as a list of assertions.",
    },
    "punct_semicolon_per_1k": {
        "above": "semicolons. A full stop does the same work and reads faster.",
        "below": "no semicolons, which is inside normal writing — check the pack is not "
                 "simply too short to measure.",
    },
    "heavy_sentence_rate": {
        "above": "sentences carrying two or more comma-clauses. Split them.",
        "below": "every sentence is a single clause. A human joins two where the second "
                 "qualifies the first.",
    },
    "mattr": {
        "above": "vocabulary churn — a different word each time where a human repeats the "
                 "plain one.",
        "below": "the same few words over and over, more than a human repeats.",
    },
    "hedges_per_1k": {
        "above": "hedged past the point of saying anything. A human states the finding and "
                 "hedges only the part that is genuinely uncertain.",
        "below": "we assert more flatly than a writer accountable for the verdict. Where "
                 "the evidence is partial, say so in the sentence instead of stating it as "
                 "settled.",
    },
}


def advice_for(measure: str, side: str) -> str:
    """The line to show a writer, or "" if the measure has none. Never raises: a missing
    entry must not turn a warning into a crash on the publish path."""
    return (ADVICE.get(measure) or {}).get(side, "")
