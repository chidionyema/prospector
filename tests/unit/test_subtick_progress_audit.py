"""Sub-tick progress: the engine must say which candidate and which check is in flight (R5).

WHY THIS EXISTS
---------------
`docs/TELEGRAM_OPERATOR_PROGRAM.md` R5 asserted that "no engine writer emits per-candidate /
per-check state, so the panel has nothing to tail". That was half wrong, and the half that was
wrong is the interesting half: `verify_search` rows have carried `candidate_id` + `check` all
along (989 of them in `store/scheduler/audit/2026-08-10.jsonl`). What was genuinely missing was

  1. the RULING — the trail showed a check going looking and never showed it deciding, and
  2. the BOUNDARIES — with no start/done rows a reader cannot tell "working" from "abandoned".

Both are now on the SAME trail as `verify_search`, written by the same `audit()`. A second
progress file was rejected: it would need its own concurrency story (the day-file is appended
by the daemon, backfills and manual CLI runs at once — see prospector/jsonl_atomic.py) and
could disagree with the trail beside it.

WHAT THE READER IS ENTITLED TO ASSUME, AND WHAT IT IS NOT
---------------------------------------------------------
It may assume a `check_result` row exists for every check that actually RAN. It may NOT assume
a `candidate_done` for every `candidate_start`: `vet_candidate` emits the closing row on its
one return path, so a raise — or a SIGKILLed daemon, which can never emit anything — leaves an
open start. `test_kill_fast_does_not_claim_checks_it_never_ran` pins the first; the staleness
rule in the gateway reader covers the second, because that case cannot be fixed by any promise
the writer makes.

ISOLATION: `_AUDIT_DIR` is monkeypatched per test. Three separate incidents in this repo ended
with pytest writing into the production audit log; the fixture is not optional politeness.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from prospector import audit as audit_mod
from prospector.config import load_config
from prospector.models import Candidate, Source
from prospector.operator import MockOperator
from prospector.retrieval import FixtureProvider
from prospector.verify import verify

SIX = ("pain_reality", "value_durability", "incumbency",
       "payer_solvency", "distribution", "legality")


@pytest.fixture()
def audit_dir(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "audit"
    monkeypatch.setattr(audit_mod, "_AUDIT_DIR", d)
    return d


def rows(audit_dir: Path, event: str = "") -> list[dict]:
    """Every intact row on the trail, optionally filtered to one event type."""
    out: list[dict] = []
    for f in sorted(audit_dir.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not event or rec.get("event") == event:
                out.append(rec)
    return out


@pytest.fixture
def cfg():
    c = load_config()
    c.retrieval.provider = "fixture"
    c.retrieval.cache = False
    c.retrieval.queries_per_check = 1
    c.retrieval.results_per_query = 1
    return c


@pytest.fixture
def cand() -> Candidate:
    return Candidate(
        title="Test Opportunity",
        one_liner="A test product",
        hypothesis="People suffer from X",
        who_pays="SMEs",
    )


PAIN_SOURCE = Source.make(url="https://pain.example.com",
                          text="acute pain confirmed by survey data")
VALUE_SOURCE = Source.make(url="https://value.example.com",
                           text="value is evaporating rapidly due to commoditisation")


def _provider() -> FixtureProvider:
    generic = [{"url": "https://any.example.com", "text": "a passage about the market"}]
    return FixtureProvider(fixtures={
        "pain": [{"url": PAIN_SOURCE.url, "text": PAIN_SOURCE.text}],
        "commoditised": [{"url": VALUE_SOURCE.url, "text": VALUE_SOURCE.text}],
        "value": [{"url": VALUE_SOURCE.url, "text": VALUE_SOURCE.text}],
        "incumbent": generic,
        "payer": generic,
        "distribution": generic,
        "legal": generic,
    })


def _router(kill_at: str = ""):
    """Rule every check `supported` unless `kill_at` names one to refute."""
    def router(system: str, user: str) -> Any:
        if "queries most likely" in system or "Write 1-3 queries" in user:
            return ["generic query"]
        if "Passages:" not in user:
            return {"verdict": "supported", "confidence": 0.9, "rationale": "ok", "citations": []}
        m = re.search(r"\[([a-f0-9]{16})\]", user)
        first_id = m.group(1) if m else ""
        if kill_at and kill_at in user:
            return {"verdict": "refuted", "confidence": 0.88,
                    "rationale": "commoditised", "citations": [first_id]}
        return {"verdict": "supported", "confidence": 0.85,
                "rationale": "confirmed", "citations": [first_id]}
    return router


# ---------------------------------------------------------------------------
# The ruling half
# ---------------------------------------------------------------------------

def test_every_check_that_runs_emits_its_ruling(audit_dir, cfg, cand):
    """One `check_result` row per check run, carrying the verdict — not just the search."""
    verify(MockOperator(router=_router()), _provider(), cfg, cand)

    got = rows(audit_dir, "check_result")
    assert got, "verify() ran but emitted no check_result rows — the trail is blind again"

    names = [r["check"] for r in got]
    assert names == sorted(set(names), key=names.index), f"duplicate check rows: {names}"
    assert set(names) <= set(SIX) | {"price_comparables"}, f"unexpected check name in {names}"

    for r in got:
        assert r["candidate_id"] == cand.candidate_id, "row not attributable to its candidate"
        assert r["verdict"], "a ruling row with no ruling is the defect this test exists for"
        assert isinstance(r["confidence"], (int, float))
        assert isinstance(r["retrieval_failed"], bool)
        assert 1 <= r["idx"] <= r["total"], f"bad progress counter {r['idx']}/{r['total']}"
        # Identity comes from audit() itself and is what makes a day-file separable by run.
        assert r["run_id"] and r["pid"] and r["seq"]


def test_the_progress_counter_is_monotonic_and_bounded(audit_dir, cfg, cand):
    """`idx`/`total` is what a panel renders as "check 4 of 7"; a wrong one misreports progress."""
    verify(MockOperator(router=_router()), _provider(), cfg, cand)
    got = rows(audit_dir, "check_result")
    idxs = [r["idx"] for r in got]
    assert idxs == list(range(1, len(idxs) + 1)), f"non-monotonic progress: {idxs}"
    assert len({r["total"] for r in got}) == 1, "total changed mid-candidate"
    assert idxs[-1] <= got[0]["total"]


def test_kill_fast_does_not_claim_checks_it_never_ran(audit_dir, cfg, cand):
    """Kill-fast returns early. The trail must stop there too, or the panel invents work.

    This is the mutation guard: emitting the row before `run_check` rather than after, or
    emitting for the whole `run_order` up front, both pass the test above and fail this one.
    """
    checks, adv, gate = verify(MockOperator(router=_router(kill_at="value_durability")),
                               _provider(), cfg, cand)
    assert gate, "fixture did not fire a gate; the test is not exercising kill-fast"

    got = rows(audit_dir, "check_result")
    assert len(got) == len(checks), (
        f"{len(got)} check_result rows for {len(checks)} checks actually run — "
        "the trail is reporting work the engine did not do"
    )
    assert [r["check"] for r in got] == [c.check_name for c in checks]
    assert got[-1]["verdict"] == "refuted"


def test_a_check_row_is_written_after_the_check_not_before(audit_dir, cfg, cand):
    """The row carries the OUTCOME, so it cannot be written before the outcome exists."""
    verify(MockOperator(router=_router()), _provider(), cfg, cand)
    for r in rows(audit_dir, "check_result"):
        assert r["verdict"] not in ("", "pending", None), (
            "a row emitted before run_check() would have no verdict to carry"
        )


# ---------------------------------------------------------------------------
# The boundary half
# ---------------------------------------------------------------------------

def test_vet_candidate_brackets_its_work_with_start_and_done(audit_dir, cfg, cand):
    """A reader tells "in flight" from "finished" by these two rows and nothing else."""
    from prospector.run import vet_candidate

    vet_candidate(cand, MockOperator(router=_router(kill_at="value_durability")),
                  _provider(), cfg, store=None, publish=False)

    starts = rows(audit_dir, "candidate_start")
    dones = rows(audit_dir, "candidate_done")
    assert len(starts) == 1 and len(dones) == 1
    assert starts[0]["candidate_id"] == dones[0]["candidate_id"] == cand.candidate_id
    assert starts[0]["title"] == cand.title
    assert starts[0]["seq"] < dones[0]["seq"], "done must not precede start on the trail"
    assert dones[0]["decision"], "a closing row with no decision closes nothing"

    # The checks that ran are bracketed BY the boundaries, which is what makes the fold work.
    checks = rows(audit_dir, "check_result")
    assert checks, "no checks between the boundaries"
    assert all(starts[0]["seq"] < c["seq"] < dones[0]["seq"] for c in checks)


def test_composite_is_omitted_not_defaulted_when_scoring_never_happened(audit_dir, cfg, cand):
    """A killed candidate never reaches scoring. `composite: 0.0` would read as a real 0.0.

    models.py:336 keeps `score_failed` precisely so "could not score" stays distinguishable
    from "scored and weak"; defaulting the field here would throw that away one layer up.
    """
    from prospector.run import vet_candidate

    vet_candidate(cand, MockOperator(router=_router(kill_at="value_durability")),
                  _provider(), cfg, store=None, publish=False)

    done = rows(audit_dir, "candidate_done")[0]
    assert done["gate"], "fixture did not kill; this test is not exercising the no-score path"
    assert "composite" not in done, (
        "composite was defaulted for a candidate that never scored — indistinguishable "
        "from a genuine 0.0"
    )
