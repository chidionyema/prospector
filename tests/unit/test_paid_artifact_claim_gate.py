"""The truth gate on the documents the buyer PAYS for (2026-08-15).

Two paths ran the SAME `verify_claims_detail` and did opposite things with the answer:

  * the marketing path (`artifacts.py::_gen_one_content`) regenerates with the violations
    fed back and DROPS the piece when they survive;
  * the paid path (`artifacts.py::_gen_one_artifact`) repairs the same way and then
    returned the content regardless, with `generate_artifacts` recording the violations in
    a `logger.info` line and nothing else — no return value, no tag, no file. "Violations
    are recorded" was a claim the code did not honour.

The lenient side was the side the buyer pays for: build_spec / gtm_plan / ops_plan fail
attempt 1 at 88-92% against 74% for marketing copy on the same checker, and the sampled
violations are real invention (a 90-day figure contradicting a cited 20-day statutory
deadline; a citation naming `voxa.com` where the source is `voxamtd.com`).

The fix, pinned below: one repair turn (already present — this file proves it is exactly
one), and on survival the content is KEPT while the PACK is held unlistable. Keeping the
document is the deliberate difference from marketing: deleting build_spec would trip
`pack_validation.py:65` as "generation produced nothing", which is an outage's signature
rather than an invention's, and it would destroy the evidence of which claim failed.

No network, no model calls: `artifacts.render` is replaced with a marker renderer so the
fake operator can be scripted per artifact type and per attempt.
"""
from __future__ import annotations

import copy
import re
import threading
from types import SimpleNamespace

import pytest

from prospector import artifacts as artifacts_mod
from prospector.artifacts import (
    CLAIM_CHECK_BLOCK_DEFAULT,
    UNVERIFIED_CLAIMS_TAG,
    claim_check_blocks_listing,
    generate_artifacts,
    unverified_claims_block_listing,
)
from prospector.config import load_config
from prospector.models import Candidate

PROSE = ("build_spec", "gtm_plan", "ops_plan")

_DRAFT_RE = re.compile(r"<<(?P<type>[a-z_]+) draft (?P<n>\d+)>>")
# The repair turn APPENDS its feedback to the same `user` string (`artifacts.py:508-509`),
# so the marker must be matched, never split on.
_ASK_RE = re.compile(r"^<artifacts type=(?P<type>[a-z_]+)>")


def _body(t: str, n: int) -> str:
    """A draft that names itself, so the claim-check call can be attributed to a type."""
    return (
        f"# <<{t} draft {n}>>\n\n"
        "## What this decides\nThe operator ships the thing.\n\n"
        "## How\nStep one, step two, step three.\n\n"
        "## Cost\nCited figures only.\n"
    )


class _FakeOperator:
    """Drafts artifacts and rules on claim-checks from a per-type script.

    ``fails_until[t]`` is the attempt number up to and including which the claim-check
    FAILS: 0 clears immediately, 1 fails the first draft only, 99 never clears.
    """

    def __init__(self, fails_until: dict[str, int]):
        self.fails_until = fails_until
        self.drafts: dict[str, int] = {}
        self.checks: dict[str, int] = {}
        self._lock = threading.Lock()

    def complete_json(self, system, user, temperature=0.0, validate=None, coerce=None,
                      **kwargs):
        ask = _ASK_RE.match(user)
        if ask is not None:
            t = ask.group("type")
            with self._lock:
                self.drafts[t] = self.drafts.get(t, 0) + 1
                n = self.drafts[t]
            data = ({"type": t, "revenue": {}, "costs": {}}
                    if t == "financial_model"
                    else {"type": t, "content": _body(t, n)})
            if validate is not None:
                validate(data)
            return data

        if user.startswith("<claim_check "):
            m = _DRAFT_RE.search(user)
            assert m is not None, "claim_check was called on copy that names no draft"
            t, n = m.group("type"), int(m.group("n"))
            with self._lock:
                self.checks[t] = self.checks.get(t, 0) + 1
            if n <= self.fails_until.get(t, 0):
                return {"pass": False,
                        "violations": [{"claim": f"{t} invented a 90-day deadline",
                                        "detail": "cited source says 20 days"}]}
            return {"pass": True, "violations": []}

        raise AssertionError(f"unexpected prompt: {user[:60]!r}")


def _marker_render(name, **kw):
    if name == "artifacts":
        return ("sys", f"<artifacts type={kw['type']}>")
    if name == "claim_check":
        return ("sys", f"<claim_check {kw['copy']}>")
    raise AssertionError(f"unexpected prompt template: {name}")


@pytest.fixture(scope="module")
def base_cfg():
    """The SHIPPED config, so the defaults under test are the ones the daemon reads.

    `load_config` resolves `REPO_ROOT / "config.yaml"`, so `monkeypatch.chdir` below cannot
    make this read a different file.
    """
    return load_config()


@pytest.fixture
def cfg(base_cfg):
    c = copy.deepcopy(base_cfg)
    # The data files are a separate register (F1/F2) and would add unrelated keys and file
    # writes to every assertion here.
    c.pack_data = {"enabled": False}

    # The human-register repair turn is a SECOND trigger on the same redraft loop, added
    # 2026-08-16. It fires on almost every draft today, because our prose sits outside the
    # human range on four measures at once, so leaving it on would make every draft count in
    # this file measure the two gates added together and `_FakeOperator`'s fixture prose
    # would decide the number. Its own behaviour is pinned in `test_prose_application.py`.
    listing = getattr(c, "listing", None)
    if isinstance(listing, dict):
        listing["human_register_repair"] = False
    elif listing is not None:
        setattr(listing, "human_register_repair", False)
    else:
        c.listing = {"human_register_repair": False}
    return c


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    """No prompt files, no network — and no writes into the tracked `store/`."""
    monkeypatch.setattr(artifacts_mod, "render", _marker_render)
    monkeypatch.chdir(tmp_path)


def _run(op, cfg):
    cand = Candidate(title="T", one_liner="o")
    results = generate_artifacts(op, cand, [], cfg=cfg)
    return cand, results


class TestTheHarnessCanDiscriminate:
    """Vacuity guards. Each of these, if false, would make every assertion below pass for
    the wrong reason."""

    def test_the_claim_check_is_switched_on_in_the_shipped_config(self, cfg):
        from prospector import evidence_budget
        assert evidence_budget.artifacts_cfg(cfg)["claim_check"] is True

    def test_a_clean_run_records_nothing_and_holds_nothing(self, cfg):
        op = _FakeOperator({})
        cand, results = _run(op, cfg)
        assert all(results[t] for t in PROSE)
        assert op.drafts == {t: 1 for t in (*PROSE, "financial_model")}
        assert UNVERIFIED_CLAIMS_TAG not in cand.tags
        assert unverified_claims_block_listing(cand) is False


class TestViolationsTriggerExactlyOneRepairTurn:
    def test_a_failing_draft_is_redrafted_once_and_rechecked_once(self, cfg):
        """Not zero (the defect would be shipping the first draft unrepaired) and not a
        loop (a second repair is another paid moat call at the point of diminishing
        returns, per `_gen_one_content`'s own budget)."""
        op = _FakeOperator({t: 99 for t in PROSE})
        _run(op, cfg)
        for t in PROSE:
            assert op.drafts[t] == 2, f"{t} drafted {op.drafts[t]} times, expected 2"
            assert op.checks[t] == 2, f"{t} checked {op.checks[t]} times, expected 2"

    def test_the_financial_model_is_never_claim_checked(self, cfg):
        """It is a JSON fill Python renders into arithmetic, not prose the model asserted."""
        op = _FakeOperator({t: 99 for t in PROSE})
        _run(op, cfg)
        assert "financial_model" not in op.checks
        assert op.drafts["financial_model"] == 1


class TestARepairThatClearsShipsNormally:
    def test_the_second_draft_ships_with_nothing_recorded_and_nothing_held(self, cfg):
        op = _FakeOperator({t: 1 for t in PROSE})
        cand, results = _run(op, cfg)
        for t in PROSE:
            assert op.drafts[t] == 2
            assert "draft 2" in results[t], f"{t} shipped the draft that FAILED the check"
        assert UNVERIFIED_CLAIMS_TAG not in cand.tags
        assert unverified_claims_block_listing(cand) is False


class TestSurvivingViolationsHoldThePackWithoutDeletingIt:
    @pytest.fixture
    def run(self, cfg):
        op = _FakeOperator({"build_spec": 99})
        return _run(op, cfg)

    def test_the_document_is_still_there(self, run):
        """The whole point of differing from the marketing path: a deleted build_spec reads
        as `pack_validation.py:65` "generation produced nothing" — an outage, not a lie."""
        _, results = run
        assert results["build_spec"].strip()
        assert "draft 2" in results["build_spec"]

    def test_the_violations_are_recorded_against_the_artifact_that_failed(self, run):
        cand, _ = run
        record = cand.tags[UNVERIFIED_CLAIMS_TAG]
        assert list(record["artifacts"]) == ["build_spec"]
        assert record["count"] == 1
        assert "20 days" in record["artifacts"]["build_spec"][0]["detail"]

    def test_the_pack_is_held_unlistable(self, run):
        cand, _ = run
        assert cand.tags[UNVERIFIED_CLAIMS_TAG]["blocks_listing"] is True
        assert unverified_claims_block_listing(cand) is True

    def test_the_clean_siblings_are_untouched(self, run):
        cand, results = run
        assert all(results[t] for t in PROSE)
        assert set(cand.tags[UNVERIFIED_CLAIMS_TAG]["artifacts"]) == {"build_spec"}


class TestTheKnobOffRestoresTodaysBehaviour:
    def test_violations_are_still_recorded_but_nothing_is_held(self, cfg):
        """Off means "do not GATE", never "do not MEASURE": the sweep that would justify
        turning it back on must keep accruing."""
        cfg.listing["claim_check_block"] = False
        op = _FakeOperator({"build_spec": 99})
        cand, results = _run(op, cfg)
        assert results["build_spec"].strip()
        assert cand.tags[UNVERIFIED_CLAIMS_TAG]["count"] == 1
        assert cand.tags[UNVERIFIED_CLAIMS_TAG]["blocks_listing"] is False
        assert unverified_claims_block_listing(cand) is False


class TestAStaleBlockCannotSurviveARegeneration:
    def test_a_clean_redraft_clears_a_previously_recorded_block(self, cfg):
        """`run.py:432` re-runs `generate_artifacts` when the artifacts were what failed. A
        block left over from the superseded draft would unlist a pack that is now clean."""
        cand = Candidate(title="T", one_liner="o")
        generate_artifacts(_FakeOperator({"build_spec": 99}), cand, [], cfg=cfg)
        assert unverified_claims_block_listing(cand) is True

        generate_artifacts(_FakeOperator({}), cand, [], cfg=cfg)
        assert UNVERIFIED_CLAIMS_TAG not in cand.tags
        assert unverified_claims_block_listing(cand) is False


class TestTheKnobIsConfigDeclaredAndOn:
    def test_the_shipped_config_ships_it_on(self, base_cfg):
        assert base_cfg.listing.get("claim_check_block") is True
        assert claim_check_blocks_listing(base_cfg) is True

    def test_a_missing_key_falls_back_to_the_code_side_default(self):
        """A config that predates the knob must not silently unbind the gate."""
        assert CLAIM_CHECK_BLOCK_DEFAULT is True
        assert claim_check_blocks_listing(None) is True
        assert claim_check_blocks_listing(SimpleNamespace(listing={})) is True

    def test_it_can_be_turned_off_from_config_alone(self):
        assert claim_check_blocks_listing(
            SimpleNamespace(listing={"claim_check_block": False})) is False
        assert claim_check_blocks_listing({"listing": {"claim_check_block": False}}) is False


class TestThePredicateIsSafeOnAnythingThePublishGateHolds:
    """`bridge.publish_pass` calls it on whatever `dossier.candidate` is; a candidate that
    never went through generation must read as CLEAR, never as blocked."""

    def test_a_candidate_with_no_tags_is_not_blocked(self):
        assert unverified_claims_block_listing(Candidate(title="T", one_liner="o")) is False
        assert unverified_claims_block_listing(SimpleNamespace(tags=None)) is False
        assert unverified_claims_block_listing(SimpleNamespace()) is False

    def test_a_malformed_record_is_not_blocked(self):
        assert unverified_claims_block_listing(
            SimpleNamespace(tags={UNVERIFIED_CLAIMS_TAG: "nonsense"})) is False
