"""A research report must say what happened to its finding, in a form a machine can check.

THE CLASS THIS CLOSES. The founder, 2026-08-21: "you are literay doing reseach identifying
wht to so and then ot doing fucckug anything", "research findings need o be fiolloweed htru",
"not just fucing wiring docs", "the gol os the rearc is to inporve the systen nont to ead
fuckig sunnaries", "we need to prevet this calls of erroes".

The failure is mechanical and therefore guardable. An experiment runs, measures something
real, writes `<name>_doc_append.md`, and then nothing in the engine changes. Nothing fails.
The report reads exactly the same whether it was acted on or forgotten, so the estate cannot
tell its shipped findings from its abandoned ones, and the same finding gets re-measured by a
later session that has no way to know it was already answered.

Measured on 2026-08-21 across the 15 reports then in the tree: 3 findings had shipped as code,
4 more needed a ticket that had never been filed, and there was no way to establish either fact
except by reading each report and then hunting the codebase for its fix.

WHAT THIS GRADES, AND WHAT IT DELIBERATELY DOES NOT. It grades whether a report NAMES its
follow-through in one of three checkable states. It does not grade whether that follow-through
was the RIGHT one -- that is a judgement, and a test that pretended to make it would be grading
a proxy. What it does refuse is the state that costs the estate money: a finding with no answer
at all, and a SHIPPED claim that points at nothing.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = REPO_ROOT / "tools" / "experiments"

MARKER = "**Follow-through:**"

# Non-vacuity floor. `test_a_directory_is_not_a_population` and `an-audit-that-crashes-reports-
# nothing` are both on this estate: a guard that grades an empty set passes and proves nothing.
# 15 reports existed when this was written; 10 leaves room to retire five without silent decay.
MIN_REPORTS = 10

# Enough words to say what changed. A one-word reason is not a reason.
MIN_REASON_CHARS = 20

# `prospector/verify.py:761`, `config.yaml:629`, `docs/ESTATE_MAP.md`. The trailing `:NNN` is
# stripped before the existence check, because a line number is not part of a path.
PATH_TOKEN = re.compile(r"[\w./\-]+\.[A-Za-z0-9]+(?::\d+)?")

TICKET = re.compile(r"#(\d+)")


def reports():
    return sorted(REPORT_DIR.glob("*_doc_append.md"))


def follow_through_lines(path):
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip().startswith(MARKER)]


def test_the_corpus_this_grades_is_not_empty():
    """This test exists so the guard below can never pass by grading nothing."""
    found = reports()
    assert len(found) >= MIN_REPORTS, (
        f"only {len(found)} *_doc_append.md under {REPORT_DIR}; "
        f"expected at least {MIN_REPORTS}. Either the reports moved and this guard now "
        f"grades an empty set, or the floor needs lowering ON PURPOSE."
    )


def test_every_report_names_its_follow_through_exactly_once():
    bad = []
    for path in reports():
        lines = follow_through_lines(path)
        if len(lines) != 1:
            bad.append(f"{path.relative_to(REPO_ROOT)}: {len(lines)} `{MARKER}` lines, expected 1")
    assert not bad, (
        "Every research report must carry exactly one line of the form:\n"
        f"  {MARKER} SHIPPED <path/that/exists.py> — what changed\n"
        f"  {MARKER} TICKET #123 — what it asks for\n"
        f"  {MARKER} NO ACTION — why the finding does not warrant a change\n\n"
        + "\n".join(bad)
    )


def test_every_follow_through_is_in_a_state_a_machine_can_check():
    bad = []
    for path in reports():
        lines = follow_through_lines(path)
        if len(lines) != 1:
            continue  # the test above owns that failure
        rel = path.relative_to(REPO_ROOT)
        body = lines[0][len(MARKER):].strip()

        if body.startswith("SHIPPED"):
            # Anti-forgery: "SHIPPED something" must not pass. At least one path named on the
            # line has to exist in the tree, so the claim points at code a reader can open.
            candidates = [t.split(":")[0] for t in PATH_TOKEN.findall(body)]
            live = [t for t in candidates if (REPO_ROOT / t).exists()]
            if not live:
                bad.append(
                    f"{rel}: SHIPPED, but no path on the line exists in the tree "
                    f"(looked at {candidates or 'no path-shaped token at all'})"
                )
        elif body.startswith("TICKET"):
            if not TICKET.search(body):
                bad.append(f"{rel}: TICKET with no #number — {body!r}")
        elif body.startswith("NO ACTION"):
            reason = body[len("NO ACTION"):].lstrip(" —-:")
            if len(reason) < MIN_REASON_CHARS:
                bad.append(
                    f"{rel}: NO ACTION needs a reason of at least {MIN_REASON_CHARS} "
                    f"characters, got {len(reason)}: {reason!r}"
                )
        else:
            # NEVER a bare pass on the unknown branch. `an-allow-list-whose-miss-case-is-silent`
            # cost this estate 10 dropped criticals over 18 hours in exactly this shape.
            bad.append(
                f"{rel}: follow-through state not recognised. It must begin with SHIPPED, "
                f"TICKET or NO ACTION. Got: {body[:80]!r}"
            )

    if bad:
        pytest.fail(
            "A research finding must say what happened to it:\n  " + "\n  ".join(bad)
        )
