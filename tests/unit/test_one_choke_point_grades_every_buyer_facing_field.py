"""Every buyer-facing field write goes through one loop: grade, repair, re-grade, record.

P2 of `docs/CONTENT_CONTRACT_PROGRAM.md`.

The defect P2 closes is not a missing repair. It is a rule written down twice. Before this,
`run.py` carried the one-liner length bar in two places twelve lines apart — once in the repair
and once in the park check — as the same sentence typed out twice. Two copies do not raise when
they drift. They just start disagreeing, and the disagreement surfaces as a pack the engine
graded clean and the publish gate refused, after the pack was paid for.

So the tests here are about IDENTITY, not about behaviour. Behaviour is pinned by
`test_a_breached_title_is_repaired_before_the_pack.py`, which still passes unchanged against the
refactor and is the evidence that nothing was lost moving the loop.

Three claims:

1. The repair and the park check ask the SAME grader object. Not an equivalent one.
2. There is exactly one repair loop in the engine. A second `for attempt in range(...)` around an
   operator call is the shape this module exists to prevent coming back.
3. A field is a declaration. Adding one means adding a `Field(...)`, and the driver picks it up
   with no other edit.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path
from unittest import mock

import pytest

from prospector import field_write as fw
from prospector import run as rn

ROOT = Path(__file__).resolve().parents[2]

CLEAN_TITLE = "Rota and shift-swap admin for NHS locum agencies"
CLEAN_LINE = ("A tool for NHS locum agencies that matches open shifts to the clinicians "
              "already on the agency's bank.")


class _Cand:
    def __init__(self, title=CLEAN_TITLE, one_liner=CLEAN_LINE):
        self.candidate_id = "cid-test"
        self.title = title
        self.one_liner = one_liner
        self.who_pays = "locum agency owners"
        self.market = "UK"
        self.tags: dict = {}


# ---- claim 1: one grader, asked by everything ------------------------------------------------

@pytest.mark.parametrize("name", ["title", "one_liner"])
def test_the_park_check_and_the_repair_share_the_grader_object(name):
    """`is`, not `==`. An equivalent grader is exactly what a drifted copy looks like."""
    field = fw.FIELDS[name]
    assert field.grade is (fw.grade_title if name == "title" else fw.grade_one_liner)
    # and the park check reaches the fields through the same registry
    assert "FIELDS" in inspect.getsource(fw.breaches) or "FIELDS[name]" in inspect.getsource(
        fw.breaches)


def test_the_engines_park_check_delegates_rather_than_regrading():
    """`_unrepaired_shelf_breaches` must not carry its own copy of any bar."""
    src = inspect.getsource(rn._unrepaired_shelf_breaches)
    body = src.split('"""')[-1]
    assert "field_write.breaches" in body
    for smell in ("check_title", "voice_breaches", "_ONE_LINER_CUT_AT", "len("):
        assert smell not in body, (
            f"the park check grades {smell!r} itself — that is the second copy P2 removed"
        )


def test_the_length_bar_is_written_exactly_once():
    """The measured defect: this sentence appeared twice in run.py, twelve lines apart."""
    phrase = "the catalogue cuts at"
    for path in ("prospector/run.py", "prospector/field_write.py"):
        text = (ROOT / path).read_text(encoding="utf-8")
        count = text.count(phrase)
        if path.endswith("field_write.py"):
            assert count == 1, f"{path} carries the length bar {count} times"
        else:
            assert count == 0, (
                f"{path} still carries its own copy of the length bar ({count})"
            )


@pytest.mark.parametrize("name", ["title", "one_liner"])
def test_the_grader_gives_the_same_answer_to_both_doors(name):
    """A value the repair would leave alone is a value the park check must pass, and the other
    way round. Same object, so this is a wiring test, not a coincidence test."""
    bad = {"title": "A" * 200, "one_liner": "You should build this yourself."}[name]
    cand = _Cand(**{name: bad})
    direct = fw.FIELDS[name].grade(bad, cand)
    via_park = [b[len(name) + 2:] for b in fw.breaches(cand, name)]
    assert direct == via_park and direct, (direct, via_park)


# ---- claim 2: exactly one repair loop ---------------------------------------------------------

def test_no_field_repair_grows_its_own_attempt_loop_again():
    """A second hand-written attempt loop around an operator call is the shape that produced
    two copies of one rule in the first place.

    Scoped to the field repairs on purpose. `_generate_pack_content` keeps its own
    `for attempt in range(_MAX_PACK_GEN_ATTEMPTS + 1)` and that is a different mechanism: it
    regenerates the whole pack, not one field, and no shelf line is reachable from it.
    """
    for fn in (rn._repair_title, rn._repair_one_liner, rn._repair_shelf_lines,
               rn._unrepaired_shelf_breaches):
        assert "for attempt in range(" not in inspect.getsource(fn), (
            f"{fn.__name__} has grown a repair loop of its own again — declare a "
            f"field_write.Field instead"
        )
    driver = re.findall(r"for attempt in range\(",
                        (ROOT / "prospector/field_write.py").read_text(encoding="utf-8"))
    assert len(driver) == 1, "the driver must be the only loop, and there must be one"


@pytest.mark.parametrize("fn", [rn._repair_title, rn._repair_one_liner])
def test_the_engines_repair_functions_are_wiring_not_loops(fn):
    body = inspect.getsource(fn).split('"""')[-1]
    assert "field_write.repair" in body
    assert "op.complete_json" not in body, "an operator call outside the choke point"


# ---- claim 3: a field is a declaration --------------------------------------------------------

def test_a_new_field_needs_no_change_to_the_driver():
    """The P2 promise in one test: declare it, and grade / repair / re-grade / record work."""
    seen: dict = {}

    field = fw.Field(
        name="headline",
        noun="headline",
        read=lambda c: getattr(c, "headline", "") or "",
        write=lambda c, v: seen.setdefault("written", v),
        grade=lambda v, c: [] if v == "good" else ["not good"],
        propose=lambda c, cur, fb, n, op: "good",
    )
    cand = _Cand()
    cand.headline = "bad"
    with mock.patch.dict(fw.FIELDS, {"headline": field}):
        out = fw.repair(cand, "headline", op=mock.Mock())
    assert out.repaired is True
    assert seen["written"] == "good"
    assert out.before == ["not good"] and out.after == []


def test_a_field_with_no_proposer_is_graded_and_reported_not_silently_passed():
    """A declared field nobody can repair yet must still show up as breached. Returning clean
    would hide it, which is how a rule ends up enforced nowhere."""
    field = fw.Field(name="subhead", noun="subhead",
                     read=lambda c: "bad", write=lambda c, v: None,
                     grade=lambda v, c: ["nope"], propose=None)
    with mock.patch.dict(fw.FIELDS, {"subhead": field}):
        out = fw.repair(_Cand(), "subhead", op=mock.Mock())
    assert out.repaired is False
    assert out.after == ["nope"]


# ---- the properties that make it safe on the money path ---------------------------------------

@pytest.mark.parametrize("name", ["title", "one_liner"])
def test_a_clean_field_costs_no_operator_call(name):
    op = mock.Mock()
    out = fw.repair(_Cand(), name, op=op)
    assert out.before == [] and out.repaired is False
    op.complete_json.assert_not_called()


def test_a_raising_operator_is_recorded_as_an_outage_not_as_a_refusal():
    """An outage and "the brain cannot satisfy this rule" need different answers. Collapsing
    them means a quota failure reads as an unfixable candidate."""
    op = mock.Mock()
    op.complete_json.side_effect = RuntimeError("all operators unavailable")
    cand = _Cand(title="A" * 200)
    out = fw.repair(cand, "title", op=op)
    assert out.failed == "all operators unavailable"
    assert out.repaired is False
    assert cand.title == "A" * 200, "a dead operator lost the candidate's own title"


def test_a_dead_brain_on_a_one_liner_is_an_outage_not_a_refusal():
    """Through the REAL `rewrite_one`, not a mock of it.

    `rewrite_one` used to catch the operator's exception and return `None` — the same answer it
    gives when the brain refuses the line. So a quota failure arrived at the choke point looking
    like "no rewrite is possible", which is the verdict that parks a candidate for good. The
    sweep still tolerates a dead call per row; it catches it at its own call site.
    """
    op = mock.Mock()
    op.complete_json.side_effect = RuntimeError("all operators unavailable")
    cand = _Cand(one_liner="You should build this yourself.")
    out = fw.repair(cand, "one_liner", op=op)
    # `rewrite_one` wraps the operator's error in `RewriteUnavailable`, so the recorded reason
    # is prefixed. What matters is that the outage reached `failed` at all, and that the brain's
    # own words survived the wrapping — assert on the cause, not on the exact sentence.
    assert out.failed and "all operators unavailable" in out.failed, out
    assert out.repaired is False
    assert cand.one_liner == "You should build this yourself."


def test_the_sweep_still_survives_one_dead_call():
    """The other half: a raise must not abort the pool, and must not be silent.

    It hands the exception BACK rather than `None`, because `None` is what a refusal returns and
    the summary prints a refused row as kept. An outage has to reach the summary as NOT
    ATTEMPTED, or a scripted caller reads a run that never got to the brain as a run that
    decided every line was fine.
    """
    import tools.sweep_shelf_copy as sweep

    op = mock.Mock()
    op.complete_json.side_effect = RuntimeError("429 overloaded")
    with mock.patch.object(sweep.log, "error") as err:
        got = sweep._rewrite_row(op, ("cid-1", "A title", "A line"))
    assert isinstance(got, sweep.RewriteUnavailable), got
    err.assert_called_once()


def test_a_proposal_that_still_breaches_is_never_written():
    op = mock.Mock()
    op.complete_json.return_value = {"title": "B" * 200}
    cand = _Cand(title="A" * 200)
    out = fw.repair(cand, "title", op=op)
    assert cand.title == "A" * 200
    assert out.repaired is False
    assert out.attempts_used == fw.MAX_TITLE_REPAIR_ATTEMPTS


def test_an_exhausted_repair_says_it_was_rejected():
    """Whatever went wrong across the attempts, the trail ends in the outcome. An empty answer
    followed by silence reads as an unfinished run rather than a refusal."""
    op = mock.Mock()
    op.complete_json.return_value = {}
    out = fw.repair(_Cand(title="A" * 200), "title", op=op)
    assert any("rejected" in t for t in out.trail), out.trail


def test_an_absent_one_liner_is_skipped_but_an_absent_title_is_not():
    """Absent is not wrong for copy nobody has written yet; a pack with no title is a defect."""
    assert fw.repair(_Cand(one_liner=""), "one_liner", op=mock.Mock()).before == []
    assert fw.breaches(_Cand(one_liner=""), "one_liner") == []
    assert fw.breaches(_Cand(title=""), "title"), "an empty title graded clean"


def test_the_one_liner_proposer_resolves_rewrite_one_at_call_time():
    """The sweep and the engine must never bind to different versions of the rewriter. Pinned
    because a `from x import y` at module scope would silently break the sweep's patch point."""
    with mock.patch("prospector.shelf_copy_repair.rewrite_one",
                    return_value=CLEAN_LINE) as rw:
        cand = _Cand(one_liner="You should build this yourself.")
        out = fw.repair(cand, "one_liner", op=mock.Mock())
    rw.assert_called_once()
    assert out.repaired is True and cand.one_liner == CLEAN_LINE


def test_the_rewrite_is_regraded_on_every_bar_not_just_the_one_that_failed():
    """A rewrite that fixes the voice and blows the length is the trade the engine used to
    make. Both bars are the same grader now, so it cannot."""
    too_long = "The agency fills its open shifts. " * 12
    assert len(too_long) > fw.ONE_LINER_CUT_AT
    with mock.patch("prospector.shelf_copy_repair.rewrite_one", return_value=too_long):
        cand = _Cand(one_liner="You should build this yourself.")
        out = fw.repair(cand, "one_liner", op=mock.Mock())
    assert out.repaired is False
    assert cand.one_liner == "You should build this yourself."


# ---- it is the contract's fields it declares --------------------------------------------------

def test_every_declared_field_is_a_field_the_content_contract_knows():
    from prospector import content_contract

    known = {f for rule in content_contract.RULES for f in rule.fields}
    assert set(fw.FIELDS) <= known, (
        f"field_write declares fields the contract has no rule for: {sorted(set(fw.FIELDS) - known)}"
    )


def test_the_constants_run_re_exports_are_the_same_objects():
    assert rn._ONE_LINER_CUT_AT == fw.ONE_LINER_CUT_AT
    assert rn._MAX_TITLE_REPAIR_ATTEMPTS == fw.MAX_TITLE_REPAIR_ATTEMPTS
