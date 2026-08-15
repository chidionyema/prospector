"""Best-effort paths may swallow the failures they were written for — not our own bugs.

MEASURED 2026-08-15. Six generation-side helpers ended in `except Exception` and returned the
value their SUCCESS path also returns: `""`, `None`, `None`, `None`, `None`, `""`. Each of
those empties is a legitimate answer somewhere (the gate is off, there is not enough measured
signal yet, harper is not installed), so a `TypeError` introduced by a refactor was
indistinguishable from the feature simply being quiet. The class of damage is specific: these
helpers feed MEASUREMENTS. A silently-dead `typicality_directive` does not read as "broken",
it reads as "verbalized sampling was on and did not move the batch"; a silently-dead
`measured_lane_quota` reads as "measured mode is running and undecided".

Three of the six are fixed by NARROWING: the expected condition still returns the designed
empty, and an unexpected exception now propagates instead of impersonating it.

The other three must NOT be narrowed, and that is a finding rather than an omission.
`record_shadow` sits inside the keep-biased prescreen gate, `incumbent_brief` and
`write_receipt` inside the generation loop; an observer or a meter that can raise is a
decision change by another name, pinned already by
`tests/unit/test_prescreen_prefilter.py::test_record_shadow_never_raises_on_a_broken_recorder`
and `tests/unit/test_landscape.py::test_never_raises`. For those the fix is the other half of
the ladder: the swallow stays total, and the failure is logged at ERROR with a traceback so a
bug of ours is attributable without ever reaching a decision. Those tests assert the log, not
a raise — a swallow with no ERROR record is the regression.
"""
from __future__ import annotations

import logging
import subprocess
from types import SimpleNamespace

import pytest

from prospector import copy_lint, diversity, landscape, lane_yield, prescreen_prefilter, sampling


class _Boom:
    """float() on this raises RuntimeError — a stand-in for a bug of ours."""

    def __float__(self):
        raise RuntimeError("our bug, not a config error")


# --------------------------------------------------------------------------- #
# sampling.typicality_directive — "" also means "the gate is off"
# --------------------------------------------------------------------------- #
def _sampling_cfg(threshold):
    return SimpleNamespace(generation={"verbalized_sampling": {
        "enabled": True, "atypical_threshold": threshold, "min_atypical_fraction": 0.4}})


def test_a_malformed_sampling_threshold_still_returns_the_empty_directive():
    assert sampling.typicality_directive(_sampling_cfg("not-a-number"), 5) == ""


def test_an_unexpected_error_in_the_sampling_directive_propagates():
    with pytest.raises(RuntimeError):
        sampling.typicality_directive(_sampling_cfg(_Boom()), 5)


# --------------------------------------------------------------------------- #
# lane_yield.measured_lane_quota — None also means "fall back to the static split"
# --------------------------------------------------------------------------- #
def test_an_unmeasurable_lane_value_still_falls_back_to_static(monkeypatch):
    monkeypatch.setattr(lane_yield, "_lane_value", lambda cfg, lanes: None)
    assert lane_yield.measured_lane_quota(SimpleNamespace(generation={}),
                                          ["a", "b"], 10) is None


def test_an_unexpected_error_computing_the_lane_quota_propagates(monkeypatch):
    def _boom(cfg, lanes):
        raise RuntimeError("our bug, not missing data")

    monkeypatch.setattr(lane_yield, "_lane_value", _boom)
    with pytest.raises(RuntimeError):
        lane_yield.measured_lane_quota(SimpleNamespace(generation={}), ["a", "b"], 10)


# --------------------------------------------------------------------------- #
# diversity.write_receipt — None also means "the meter is switched off"
# --------------------------------------------------------------------------- #
def _diversity_cfg(tmp_path):
    return SimpleNamespace(generation={"diversity_meter": True}, store_dir=str(tmp_path))


def test_the_diversity_meter_stays_off_without_the_flag(tmp_path):
    cfg = SimpleNamespace(generation={}, store_dir=str(tmp_path))
    assert diversity.write_receipt(cfg, "generated", []) is None


def test_a_broken_diversity_meter_is_swallowed_but_logged_at_error(tmp_path, monkeypatch,
                                                                   caplog):
    """It must not break generation — and it must not be silent about the missing stage."""
    def _boom(*a, **k):
        raise RuntimeError("our bug, not a disk failure")

    monkeypatch.setattr(diversity, "batch_report", _boom)
    with caplog.at_level(logging.ERROR, logger="prospector"):
        assert diversity.write_receipt(_diversity_cfg(tmp_path), "generated", []) is None

    errs = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errs, "a dead meter that logs nothing is indistinguishable from a meter that is off"
    assert errs[0].exc_info is not None, "no traceback means the bug is not attributable"


# --------------------------------------------------------------------------- #
# prescreen_prefilter.record_shadow — None also means "shadow mode is off"
# --------------------------------------------------------------------------- #
def _record(cfg=None):
    return prescreen_prefilter.record_shadow(
        cfg, None, llm_keep=True, llm_score=1.0, llm_reason="", llm_called=True)


def test_an_undeliverable_shadow_row_still_returns_none(monkeypatch):
    def _bad(cfg):
        raise OSError("log path is read-only")

    monkeypatch.setattr(prescreen_prefilter, "get_shadow", _bad)
    assert _record() is None


def test_a_broken_shadow_recorder_is_swallowed_but_logged_at_error(monkeypatch, caplog):
    """The gate must never see it — and the E6 log must not lose rows silently."""
    def _boom(cfg):
        raise RuntimeError("our bug, not a disk failure")

    monkeypatch.setattr(prescreen_prefilter, "get_shadow", _boom)
    with caplog.at_level(logging.ERROR, logger="prospector"):
        assert _record() is None

    errs = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errs, "a recorder that drops every row must say so"
    assert errs[0].exc_info is not None, "no traceback means the bug is not attributable"


# --------------------------------------------------------------------------- #
# copy_lint.grammar_findings — None also means "harper-cli is not installed"
# --------------------------------------------------------------------------- #
_LONG = "This is a sufficiently long piece of buyer facing prose to reach the sixty char floor."


def test_a_harper_failure_still_reports_unavailable(monkeypatch):
    monkeypatch.setattr(copy_lint, "harper_path", lambda: "/bin/true")

    def _timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="harper-cli", timeout=1)

    monkeypatch.setattr(copy_lint.subprocess, "run", _timeout)
    assert copy_lint.grammar_findings({"body": _LONG}) is None


def test_an_unexpected_error_in_the_grammar_check_propagates(monkeypatch):
    monkeypatch.setattr(copy_lint, "harper_path", lambda: "/bin/true")

    def _boom(*a, **k):
        raise RuntimeError("our bug, not a missing binary")

    monkeypatch.setattr(copy_lint.subprocess, "run", _boom)
    with pytest.raises(RuntimeError):
        copy_lint.grammar_findings({"body": _LONG})


# --------------------------------------------------------------------------- #
# landscape.incumbent_brief — "" also means "the gate is off / no topic"
# --------------------------------------------------------------------------- #
def _landscape_cfg(tmp_path):
    return SimpleNamespace(generation={"incumbent_seed": {"enabled": True}},
                           store_dir=str(tmp_path))


def test_incumbent_seeding_stays_empty_when_the_gate_is_off(tmp_path):
    cfg = SimpleNamespace(generation={}, store_dir=str(tmp_path))
    assert landscape.incumbent_brief(cfg, signal_text="x") == ""


def test_an_expected_incumbent_seed_failure_still_returns_empty(tmp_path, monkeypatch):
    def _bad(*a, **k):
        raise ValueError("bad config value")

    monkeypatch.setattr(landscape, "_topic", _bad)
    assert landscape.incumbent_brief(_landscape_cfg(tmp_path), signal_text="x") == ""


def test_broken_incumbent_seeding_is_swallowed_but_logged_at_error(tmp_path, monkeypatch,
                                                                  caplog):
    """The tick must survive it — and "enabled but dead" must not look like "no incumbents"."""
    def _boom(*a, **k):
        raise RuntimeError("our bug, not a retrieval outage")

    monkeypatch.setattr(landscape, "_topic", _boom)
    with caplog.at_level(logging.ERROR, logger="prospector"):
        assert landscape.incumbent_brief(_landscape_cfg(tmp_path), signal_text="x") == ""

    errs = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errs, "an enabled seed that never produces a brief must say so"
    assert errs[0].exc_info is not None, "no traceback means the bug is not attributable"


def test_a_corrupt_incumbent_cache_is_a_cold_cache_that_says_so(tmp_path, monkeypatch, caplog):
    """The inner cache read IS narrowed: unreadable file / unparseable JSON only, at ERROR.

    A cache that silently reads as cold on every call turns "one fetch per audience per ttl"
    into "one fetch per call" — a cost change with no other symptom anywhere in the run.
    """
    monkeypatch.delenv("PROSPECTOR_GENERATION_ARTIFACT_DIR", raising=False)
    (tmp_path / "incumbent_cache.json").write_text("not json", encoding="utf-8")
    monkeypatch.setattr(landscape, "_fetch_brief", lambda cfg, icfg, topic: "FRESH")

    with caplog.at_level(logging.ERROR, logger="prospector"):
        assert landscape.incumbent_brief(_landscape_cfg(tmp_path), sector="veterinary") == "FRESH"

    assert [r for r in caplog.records if r.levelno >= logging.ERROR]
