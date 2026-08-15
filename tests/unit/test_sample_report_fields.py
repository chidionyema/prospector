"""The free sample's legacy fields go through the publish pass, like every other buyer string.

`tools/make_sample_report.report_fields` is what bakes `src/data/sample-report.json`, which five
storefront components read -- including `HeroEvidenceStrip`, which is on the HOME page. Until
2026-08-15 it emitted check rationales with `nodash` alone, so the one gate that removes engine
machinery from buyer prose (`plain_text.publish_pass`, "the single gate every engine-authored
string passes before a buyer can read it") was skipped for the page whose whole argument is that
every claim is traceable.

Measured on the baked fixture that day, before the fix: 30 raw bracket ids across 9 of 9 check
rationales, and `incumbency` ending mid-citation on `[c33885f45`. These pin the property, not the
count -- a fixture regenerated from a different dossier must still be clean.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from make_sample_report import readable, report_fields  # noqa: E402

# Deliberately looser than the engine's own id pattern: it also catches the TRUNCATED stub
# (`[c33885f45`, nine hex digits and no closing bracket), which is the shape that reads worst on
# the page -- a full id is at least a pointer somebody could look up.
BRACKET_ID = re.compile(r"\[[0-9a-f]{6,16}(?:\s*,\s*[0-9a-f]{6,16})*\]?")

DOSSIER = {
    "created_at": "2026-08-01T00:00:00Z",
    "candidate": {
        "title": "T",
        "one_liner": "A tool for subcontractors",
        "who_pays": "Subcontractors chasing retention",
        "why_now": "The 2024 reforms",
        "tags": {},
    },
    "score": {"scores": {}},
    "checks": [{
        "check_name": "incumbency",
        "verdict": "unverifiable",
        "confidence": 0.4,
        # Every shape the pass is meant to remove, in one string: a bracketed run of full ids, a
        # confidence float, and a citation truncated mid-id at the end.
        "rationale": ("No incumbent is described [b6a332340275517f, 736c566d3d66530a], "
                      "confidence 0.4. One passage discusses retention in the UK [c33885f45"),
        "sources": [{"source_id": "b6a332340275517f", "url": "https://payapps.com/x",
                     "text": "A Guide To Retention In Construction\nBody."}],
    }],
    "adversarial": {"kill_case": "It could fail [736c566d3d66530a].", "decisive": True},
}


@pytest.fixture(scope="module")
def fields() -> dict:
    return report_fields("deadbeefdeadbeef", DOSSIER)


def test_no_passage_id_reaches_a_check_rationale(fields):
    rationale = fields["checks"][0]["rationale"]
    assert not BRACKET_ID.findall(rationale), rationale


def test_a_citation_truncated_mid_id_does_not_reach_the_page(fields):
    """The stub is the worst of the three: a full id is a pointer, nine hex digits are not.

    `publish_pass` repairs the sentence the truncation broke rather than leaving it hanging, so
    the assertion is on the ending too -- dropping the stub and shipping "...in the UK" would
    only move the defect.
    """
    rationale = fields["checks"][0]["rationale"]
    assert "c33885f45" not in rationale
    assert rationale.endswith("."), rationale


def test_the_confidence_float_stays_out_of_the_prose(fields):
    # The panel prints `confidence` as its own typed field; the same number spelled out mid
    # sentence is machinery, and "confidence 0.4" argues against the verdict it is attached to.
    assert "0.4" not in fields["checks"][0]["rationale"]
    assert fields["checks"][0]["confidence"] == 0.4, "the typed field is untouched"


def test_the_rationale_is_not_blanked_by_the_cleaning(fields):
    """`sentences=True` returns "" when no complete sentence survives, which would be silent.

    A rationale cleaned to nothing renders as an empty check on the page -- worse than the raw
    ids, and invisible in a diff of counts. This is the assertion that stops a future widening
    of the pass from emptying the sample instead of tidying it.
    """
    assert "No incumbent is described" in fields["checks"][0]["rationale"]


def test_the_card_lines_survive_ending_on_a_noun(fields):
    """Why they are passed `sentences=False`.

    "A tool for subcontractors" is a complete card line and not a sentence. Under the
    complete-sentence rule it would come back empty, so the home page's evidence strip would
    lose its one-liner to a cleaning pass -- the failure this parameter exists to avoid.
    """
    assert fields["oneLiner"] == "A tool for subcontractors"
    assert fields["whoPays"] == "Subcontractors chasing retention"


def test_it_is_still_json_serialisable_and_carries_the_shape_the_components_read(fields):
    # The other half of `report_fields`'s contract: five components and their test read these
    # keys by name, so the pass must not have changed the SHAPE while cleaning the values.
    json.dumps(fields)
    for key in ("id", "title", "oneLiner", "whoPays", "whyNow", "verifiedAt", "supported",
                "total", "sourceCount", "scores", "premortem", "adversarial", "checks"):
        assert key in fields, key


def test_readable_is_idempotent():
    # `resolve_citations` runs it and so does `report_fields`; some strings meet it twice.
    once = readable("A claim [b6a332340275517f], confidence 0.4.", sentences=True)
    assert readable(once, sentences=True) == once
