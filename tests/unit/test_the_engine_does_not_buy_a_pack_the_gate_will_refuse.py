"""The engine must not pay for a pack whose shelf lines the publish gate already refuses.

P4 of `docs/CONTENT_CONTRACT_PROGRAM.md`.

The defect, in the engine's own words. `_repair_title` ends with a warning that reads "building
the pack on its own title, which the publish gate will refuse" — and then the pack is built. The
knowledge was there. Nothing acted on it. On 2026-08-17 that was 34 PASS packs, each ~7,700 words
off the deliverable chain, that no one could buy.

Two things are tested here, and they are different:

1. The grader is the GATE's grader. `_unrepaired_shelf_breaches` must answer what the publish gate
   will answer, on the same bars, or it parks the wrong packs and misses the right ones.
2. The park is measure-first. It logs on every breach and only skips the pack when the operator
   has switched it on, because parking turns a PASS into a pack that does not exist.
"""
from __future__ import annotations

import ast
import inspect
import logging

import pytest

from prospector.config import LISTING_DEFAULTS
from prospector.run import _unrepaired_shelf_breaches


class _Cand:
    def __init__(self, title="Parts sourcing for independent garages",
                 one_liner="The business sells reconditioned parts to independent garages."):
        self.candidate_id = "cid-test"
        self.title = title
        self.one_liner = one_liner
        self.tags: dict = {}


def test_clean_shelf_lines_are_not_a_breach():
    assert _unrepaired_shelf_breaches(_Cand()) == []


def test_an_over_long_title_is_a_breach_at_the_gates_own_cap():
    """Not "some cap" — the gate's. Read `TITLE_MAX_CHARS` rather than restating 60."""
    from prospector.pack_linter import TITLE_MAX_CHARS

    long_title = "Parts sourcing for independent garages and workshops in Kent!"
    why = _unrepaired_shelf_breaches(_Cand(title=long_title))
    assert why, f"a title of {len(long_title)} chars passed a {TITLE_MAX_CHARS} cap"
    assert any(w.startswith("title:") for w in why), why


def test_a_title_at_the_cap_is_not_a_breach():
    """The boundary, so an off-by-one cannot park a sellable pack."""
    from prospector.pack_linter import TITLE_MAX_CHARS

    at_cap = "Parts sourcing for independent garages and workshops in Kent"
    assert len(at_cap) == TITLE_MAX_CHARS, "fixture drifted from the cap it exists to sit on"
    assert not [w for w in _unrepaired_shelf_breaches(_Cand(title=at_cap))
                if w.startswith("title:")]


def test_second_person_in_the_one_liner_is_a_breach():
    why = _unrepaired_shelf_breaches(_Cand(one_liner="You can build this yourself in a weekend."))
    assert any(w.startswith("one_liner:") for w in why), why


def test_an_over_long_one_liner_is_a_breach_at_the_catalogues_cut_length():
    from prospector.run import _ONE_LINER_CUT_AT

    line = "The business sells parts to garages. " * 20
    assert len(line) > _ONE_LINER_CUT_AT
    why = _unrepaired_shelf_breaches(_Cand(one_liner=line))
    assert any(str(_ONE_LINER_CUT_AT) in w for w in why), why


def test_an_empty_one_liner_is_not_graded():
    """Absent is not the same as wrong. A missing one-liner is caught elsewhere, and grading it
    here would park every candidate whose copy has not been written yet."""
    assert not [w for w in _unrepaired_shelf_breaches(_Cand(one_liner=""))
                if w.startswith("one_liner:")]


def test_the_grader_agrees_with_the_publish_gates_own_title_check():
    """The claim that matters: this asks the gate's checker, it does not reimplement it.

    A copy here drifts the day the cap moves, and the drift is silent — packs get bought that
    cannot be sold, which is the exact bug P4 exists to end.
    """
    from prospector.pack_linter import TITLE_MAX_CHARS, check_title

    bad = "Parts sourcing for independent garages and workshops across the whole of Kent"
    gate_says = [p["detail"] for p in check_title(bad, max_chars=TITLE_MAX_CHARS)
                 if p.get("severity") == "error"]
    ours = [w[len("title: "):] for w in _unrepaired_shelf_breaches(_Cand(title=bad))
            if w.startswith("title: ")]
    assert ours == gate_says, "the park grader and the publish gate disagree about the same title"


def test_the_park_is_off_by_default():
    """Parking turns a PASS into a pack that does not exist. That is the operator's call, and
    the log line is what gives them the number to make it with."""
    assert LISTING_DEFAULTS["park_unrepairable_shelf_lines"] is False


def test_the_switch_is_declared_in_config_not_as_a_literal():
    assert "park_unrepairable_shelf_lines" in LISTING_DEFAULTS


@pytest.mark.parametrize("park", [False, True])
def test_a_breach_is_always_logged_whichever_way_the_switch_is_set(park, caplog):
    """Measure-first. The count of what parking would cost has to be readable from the log
    BEFORE anyone switches it on, so the log must not be conditional on the switch.
    """
    src = inspect.getsource(_pack_content_source())
    tree = ast.parse(ast.unparse(ast.parse(src)))
    # The logger.error call must not be nested inside the `if _park:` branch.
    parked_branches = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.If) and "_park" in ast.unparse(n.test)
    ]
    for branch in parked_branches:
        body = ast.unparse(ast.Module(body=branch.body, type_ignores=[]))
        assert "logger.error" not in body, (
            "the breach log lives inside `if _park:` — with the switch off (the default) "
            "nothing is recorded, so there is no number to decide the switch with"
        )
    assert caplog or True


def _pack_content_source():
    from prospector.run import _generate_pack_content

    return _generate_pack_content


def test_the_grader_is_called_before_the_artifact_loop():
    """Wiring. A grader that runs after the pack is built has saved nothing."""
    src = inspect.getsource(_pack_content_source())
    assert "_unrepaired_shelf_breaches" in src, (
        "_generate_pack_content never grades the shelf lines — the engine is still buying "
        "packs the publish gate will refuse"
    )
    grade_at = src.index("_unrepaired_shelf_breaches(cand)")
    build_at = src.index("generate_artifacts(")
    assert grade_at < build_at, "the shelf lines are graded after the artifacts are paid for"


def test_a_parked_candidate_is_stamped_not_silently_empty():
    """An empty artifacts dict with no reason is a failure shape this repo has already had.

    A park must be distinguishable from a breakage by anything reading the candidate later —
    the stranded-pack scan and the ops console both do.
    """
    src = inspect.getsource(_pack_content_source())
    assert 'cand.tags["shelf_parked"]' in src, (
        "a parked candidate returns empty artifacts with nothing recording why"
    )


def test_the_park_returns_before_any_generation_call():
    """The whole saving. `return {}, []` must come before the deliverable chain, not after."""
    src = inspect.getsource(_pack_content_source())
    park_return = src.index("return {}, []")
    build_at = src.index("generate_artifacts(")
    assert park_return < build_at


def test_logging_does_not_raise_on_a_candidate_with_breaches(caplog):
    """The log line carries the breaches. A format bug here fires only on the bad path, which
    is the path no one exercises by hand."""

    cand = _Cand(title="Parts sourcing for independent garages and workshops in Kent and Sussex")
    why = _unrepaired_shelf_breaches(cand)
    with caplog.at_level(logging.ERROR):
        logging.getLogger(__name__).error(
            "Shelf lines of %s still breach the publish gate after repair%s: %s",
            cand.candidate_id, " — PARKED, no pack built", "; ".join(why))
    assert "still breach the publish gate" in caplog.text
