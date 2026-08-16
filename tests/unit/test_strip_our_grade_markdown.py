"""The engine-grade strip, pinned to the renderer it has to agree with.

`render_markdown(..., include_our_grade=False)` keeps our scoresheet out of every pack
generated from 2026-08-15 onward. It cannot reach the 61 packs already on the shelf: their
`index.html` and `Complete_Pack.pdf` are RENDERED, so nothing can be edited in place, and
they are re-rendered from their own pre-conversion `.md` — markdown written before the fix
existed. `strip_our_grade_markdown` is that same removal expressed on the shipped document.

Two functions doing one job is a drift risk, so the load-bearing test here is the PAIRING
test: strip the `include_our_grade=True` render and you must get the `include_our_grade=False`
render, character for character. Measured 2026-08-16 over all 75 stored PASS dossiers: 75
matched, 0 mismatched, 0 no-ops.
"""
import glob
import json

import pytest

from prospector import pack_manifest
from prospector.dossier import render_markdown, strip_our_grade_markdown

SCORED = """\
# Every check, in full

Some prose about the market.

---
## How it scored

**Overall: 3.6500** (each line is rated out of 5, then weighted)

| What we rated | Score | Why |
|---------------|------:|-----|
| How badly it hurts | 4/5 | Councils are already paying for this by hand. |
| How provable the money is | 3/5 | Two cited invoices. |

---
## Why this passed

Survived all gates; composite 3.6500; 5 grounded-supported check(s) (moat grounded: 1).

---
## Every source we used

- <https://example.gov.uk/a>
"""


def test_the_scoresheet_and_the_composite_both_go():
    out = strip_our_grade_markdown(SCORED)
    assert out is not None
    assert "How it scored" not in out
    assert "3.6500" not in out
    assert "composite" not in out.lower()
    # and the sections either side are untouched
    assert "## Why this passed" in out
    assert "Survived all gates; 5 grounded-supported check(s) (moat grounded: 1)." in out
    assert "## Every source we used" in out
    assert "https://example.gov.uk/a" in out


def test_a_clean_report_comes_back_none():
    """The None contract `patched_md` relies on, and the idempotency it buys: running the
    backfill twice must not rewrite a pack it already corrected."""
    once = strip_our_grade_markdown(SCORED)
    assert strip_our_grade_markdown(once) is None
    assert strip_our_grade_markdown("# A report with no grade in it\n\nProse.\n") is None


def test_the_signage_pack_keeps_its_spec():
    """`_COMPOSITE_CLAUSE` is `\\bcomposite\\s+\\d`, which a pack about signage matches in
    good faith. The scrub is scoped to the pass-reason line for exactly this reason: a
    backfill that silently edits a buyer's spec sheet is a worse defect than the leak it
    was sent to fix. This string is the shape that produced the false positives when the
    engine-leak token list was first drafted (`check_engine_leak`, 2026-08-15)."""
    doc = SCORED.replace("Some prose about the market.",
                         "Panels are 3mm aluminium composite 3050 x 1500, cut to size.")
    out = strip_our_grade_markdown(doc)
    assert out is not None
    assert "aluminium composite 3050 x 1500" in out


def test_a_report_with_only_the_composite_clause_is_still_stripped():
    """A KILL-shaped or hand-edited report may carry the reason line without the table.
    Anchoring the strip on the table would leave the figure the founder actually quoted."""
    doc = "## Why this passed\n\nSurvived all gates; composite 2.9500; 8 checks.\n"
    out = strip_our_grade_markdown(doc)
    assert out == "## Why this passed\n\nSurvived all gates; 8 checks.\n"


# ---------------------------------------------------------------------------
# The pairing test — the one that stops the two implementations drifting
# ---------------------------------------------------------------------------

def _stored_dossiers():
    return sorted(glob.glob("store/dossiers/*.pass.json"))


def test_strip_matches_what_the_renderer_omits():
    """Over every stored PASS dossier on this disk. Skipped rather than failed where the
    store is absent: a fresh worktree has no dossiers, and a data-dependent test that fails
    on an empty store reports a checkout problem as a code defect."""
    paths = _stored_dossiers()
    if not paths:
        pytest.skip("no stored PASS dossiers on this checkout")

    mismatched = []
    for path in paths:
        d = pack_manifest.dossier_from_dict(json.loads(open(path).read()))
        with_grade = render_markdown(d, include_our_grade=True)
        without = render_markdown(d, include_our_grade=False)
        if with_grade == without:
            continue  # nothing to strip; the pairing claim is vacuous for this record
        if strip_our_grade_markdown(with_grade) != without:
            mismatched.append(path)

    assert not mismatched, (
        f"{len(mismatched)} of {len(paths)} dossiers strip to something other than the "
        f"renderer's own omission: {mismatched[:3]}")
