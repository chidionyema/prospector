"""`copy_lint`'s abstraction-and-hedging check, and the two claims the module made about it.

WHY THIS FILE EXISTS
--------------------
`copy_lint.py` carried three ways for a reader to believe the wrong thing about one function:

1. `check_register` had no caller anywhere in the repo, so it looked live and was not;
2. it NAME-COLLIDED with `register_lint.check_register`, a different check measuring
   different things, so a reader who found one had no way to know which they had found;
3. its own comment cited `tests/unit/test_copy_lint_register.py` -- this file -- which did
   not exist, for the claim that the `str.endswith` rewrite "matches the same words" as the
   quadratic regex alternation it replaced for speed.

(1) and (2) are answered by the rename to `check_abstraction_and_hedging` plus the docstring
recording that it is unwired and why. (3) is answered here: the equivalence is now measured
rather than asserted, over the corpus the check actually grades.

Measured for (1) on 2026-08-15, over the whole repo, `prospector/`, `tools/`, `scripts/` and
`tests/` included:

    $ rg -n 'check_register' .
    ./prospector/register_lint.py:445:def check_register(...)
    ./prospector/copy_lint.py:558:def check_register(...)
    ./tests/unit/test_register_lint.py:{13,81,98,100,122,125,130}

-- `register_lint`'s has tests and no production caller; `copy_lint`'s had neither.
"""
import re
from pathlib import Path

from prospector import copy_lint, register_lint

REPO = Path(__file__).resolve().parents[2]

# Long enough to clear the 120-word floor the check needs before a rate means anything.
FILLER = ("The service files the appeal for the carer and chases the council until it "
          "answers. A carer signs once, and the letters go out on the same day. ") * 8


# --- (3) the claim the false citation was standing in for ---------------------------------

def test_the_endswith_form_matches_the_regex_alternation_it_replaced():
    """The rewrite was made for SPEED, and speed is not a licence to change the answer.

    The regex form is the one the comment says was killed at two minutes on the 140-bundle
    sweep. It is fine on a fixture, which is exactly why it can be used as the oracle here.
    """
    alternation = re.compile(
        r"\b[A-Za-z][A-Za-z'\-]*(?:" +
        "|".join(sorted(set(s.rstrip("s") for s in copy_lint._NOMINALISATION_SUFFIXES),
                        key=len, reverse=True)) + r")s?\b")

    corpus = [
        FILLER,
        "The implementation of the requirement produced a reduction in duration and a "
        "significant improvement in the quality of the submission process.",
        "Onboarding drops from six weeks to four days because one form replaced three.",
        "Compliance, insurance and maintenance are ordinary words for this buyer.",
        "Cities and counties and charities and entities and utilities and facilities.",
        "The commission's decision on the transaction was a condition of the acquisition.",
        "",
        "No suffixes here at all, just short plain words that do the job.",
    ]
    for text in corpus:
        body = copy_lint._strip_code(text)
        tokens = copy_lint._WORD_TOKEN_RE.findall(body)
        by_regex = [
            tok for tok in tokens
            if alternation.fullmatch(tok)
            and len(tok) >= copy_lint._MIN_NOMINALISATION_LEN
            and tok.lower() not in copy_lint._NOMINALISATION_ALLOW
        ]
        _pct, by_endswith = copy_lint.nominalisation_rate(text)
        assert by_endswith == by_regex, f"the two forms disagree on {text[:60]!r}"


# --- (2) the collision is gone, and the two checks are genuinely different -----------------

def test_the_name_collision_with_register_lint_is_gone():
    """One name, one function. `copy_lint` must no longer export `check_register`."""
    assert not hasattr(copy_lint, "check_register")
    assert hasattr(copy_lint, "check_abstraction_and_hedging")
    assert hasattr(register_lint, "check_register")


def test_the_two_checks_are_not_duplicates_and_report_different_findings():
    """The reason the resolution was a rename and not a deletion.

    Deleting a duplicate is right; deleting a check nothing else performs is a silent
    capability removal. The two are handed the same text and asked what they find.
    """
    texts = {"03_Go_To_Market.md": FILLER + (
        "The implementation of the requirement produced a reduction in duration, and it "
        "could be argued that this is arguably somewhat significant. Potentially the "
        "optimisation of the allocation is essentially a consideration for the "
        "organisation, and it may be that the utilisation of the provision is basically "
        "an improvement in the presentation of the information.")}

    mine = {p["check"] for p in copy_lint.check_abstraction_and_hedging(texts)}
    theirs = {p["check"] for p in register_lint.check_register(texts)}
    assert mine, "the fixture must trip the check it is written for"
    assert not (mine & theirs), (
        f"overlapping findings would make this a duplicate: {mine & theirs}")


# --- (1) it is unwired, and this file is the honest record of that ------------------------

def test_the_check_is_still_unwired_and_this_is_the_receipt():
    """A pin on the FACT, not on the desirability of the fact.

    If somebody wires it into `pack_linter` this fails, and the docstring saying it is
    unwired -- which is the only thing stopping the next reader assuming it is live -- gets
    corrected in the same change. That is the whole job of this assertion.
    """
    callers = []
    for root in ("prospector", "tools", "scripts"):
        for path in sorted((REPO / root).rglob("*.py")):
            if path.name == "copy_lint.py":
                continue  # the definition and its own docstring
            for n, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
                if "check_abstraction_and_hedging" in line:
                    callers.append(f"{path.relative_to(REPO)}:{n}")
    assert not callers, (
        "it is wired now -- update the docstring in copy_lint.py that says it is not: "
        + "; ".join(callers))


# --- the check's own behaviour, so wiring it later is a one-line change --------------------

def test_flat_abstract_prose_is_flagged_and_plain_prose_is_not():
    zombie = {"03_Go_To_Market.md": (
        "The implementation of the requirement produced a reduction in duration. " * 12)}
    plain = {"03_Go_To_Market.md": FILLER}
    assert any(p["check"] == "nominalisation"
               for p in copy_lint.check_abstraction_and_hedging(zombie))
    assert not [p for p in copy_lint.check_abstraction_and_hedging(plain)
                if p["check"] == "nominalisation"]


def test_hedging_is_counted_and_stated_uncertainty_is_not():
    """The distinction the prompts were rewritten around: naming a limit is not hedging."""
    hedged = {"03_Go_To_Market.md": FILLER + (
        "It could be argued that this is arguably somewhat potentially relevant. "
        "It may be that the result is essentially basically fairly conceivable. ")}
    honest = {"03_Go_To_Market.md": FILLER + (
        "One source, dated 2024, says the council pays this rate. Nothing corroborates it, "
        "and we found no second page that names a figure at all. ")}
    assert any(p["check"] == "hedging"
               for p in copy_lint.check_abstraction_and_hedging(hedged))
    assert not [p for p in copy_lint.check_abstraction_and_hedging(honest)
                if p["check"] == "hedging"]


def test_a_data_artifact_is_never_graded_as_writing():
    """`is_prose_artifact` is the single definition of what may be graded; a CSV of column
    headers scoring badly on nominalisation is the category error that delisted a live pack.
    """
    csv = {"assumptions.csv": "section,key,label,value\n" * 60}
    assert copy_lint.check_abstraction_and_hedging(csv) == []


def test_prose_under_the_word_floor_is_not_rated():
    """A rate over 40 words is noise, and noise in a warning trains people to ignore it."""
    short = {"03_Go_To_Market.md": "The implementation of the requirement was a reduction."}
    assert copy_lint.check_abstraction_and_hedging(short) == []


def test_every_finding_is_a_warning_and_none_can_unlist_a_pack():
    """House doctrine, stated in the section comment: flat prose is a quality defect, not a
    truth defect, and this repo's gates exist for truth."""
    texts = {"03_Go_To_Market.md": FILLER + (
        "The implementation of the requirement produced a reduction in duration, and it "
        "could be argued that this is arguably somewhat potentially significant. " * 3)}
    problems = copy_lint.check_abstraction_and_hedging(texts)
    assert problems
    assert all(p["severity"] == "warning" for p in problems), [p["severity"] for p in problems]
