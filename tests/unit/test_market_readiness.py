"""The Market-Readiness Gate (spec §Gate).

The gate's job is to make "we opened a market" a measured claim. These tests pin the
two ways it could be cheated: opening on a stale measurement, and clearing a bar by
lowering it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from prospector import markets as mk
from prospector.config import load_config
from prospector.models import Candidate, CheckResult, Decision, Dossier, Source, Verdict

CALIBRATION_DIR = Path(__file__).resolve().parents[2] / "markets" / "calibration"


def _outcome(expected="pass", actual="pass", grounded=6, total=6,
             auth=4, srcs=6, title="T") -> mk.ProbeOutcome:
    return mk.ProbeOutcome(title=title, expected=expected, actual=actual,
                           grounded_checks=grounded, total_checks=total,
                           authority_sources=auth, total_sources=srcs)


def _healthy_outcomes() -> list[mk.ProbeOutcome]:
    return [_outcome("pass", "pass", title="a"), _outcome("pass", "pass", title="b"),
            _outcome("kill", "kill", title="c"), _outcome("kill", "kill", title="d")]


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def test_a_healthy_probe_is_ready():
    cfg = load_config()
    r = mk.evaluate(cfg, "us", _healthy_outcomes())
    assert r.ready, r.failures
    assert r.metrics["discrimination"] == 1.0
    assert r.metrics["pass_rate"] == 0.5


def test_ungrounded_market_is_not_ready():
    """The core failure: the engine cannot find evidence in this jurisdiction."""
    outcomes = [_outcome("pass", "kill", grounded=1, total=6, title="a"),
                _outcome("kill", "kill", grounded=0, total=6, title="b")]
    r = mk.evaluate(load_config(), "us", outcomes)
    assert not r.ready
    assert any("grounding_rate" in f for f in r.failures)


def test_market_grounded_only_on_junk_domains_is_not_ready():
    outcomes = [_outcome("pass", "pass", auth=0, srcs=10, title="a"),
                _outcome("kill", "kill", auth=0, srcs=10, title="b")]
    r = mk.evaluate(load_config(), "us", outcomes)
    assert not r.ready
    assert any("authority_rate" in f for f in r.failures)


def test_market_that_reads_the_evidence_wrong_is_not_ready():
    outcomes = [_outcome("pass", "kill", title="a"), _outcome("pass", "kill", title="b"),
                _outcome("kill", "kill", title="c"), _outcome("kill", "kill", title="d")]
    r = mk.evaluate(load_config(), "us", outcomes)
    assert not r.ready
    assert any("discrimination" in f for f in r.failures)


def test_market_that_kills_everything_is_not_ready():
    outcomes = [_outcome("kill", "kill", title=str(i)) for i in range(4)]
    r = mk.evaluate(load_config(), "us", outcomes)
    assert not r.ready
    assert any("pass_rate" in f for f in r.failures)


def test_all_defer_measures_an_outage_not_a_market():
    """DEFER is infrastructure failure. It must not be scored as a wrong answer, and it
    must not let a market through either."""
    outcomes = [_outcome("pass", "defer", title="a"), _outcome("kill", "defer", title="b")]
    r = mk.evaluate(load_config(), "us", outcomes)
    assert not r.ready
    assert any("DEFERRED" in f for f in r.failures)
    assert r.metrics["defer_rate"] == 1.0


def test_defers_are_excluded_from_discrimination():
    outcomes = _healthy_outcomes() + [_outcome("pass", "defer", title="e")]
    r = mk.evaluate(load_config(), "us", outcomes)
    assert r.metrics["discrimination"] == 1.0  # the defer neither helps nor hurts
    assert r.metrics["defer_rate"] == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# The bar cannot be lowered
# ---------------------------------------------------------------------------

def test_a_market_may_raise_its_bars_but_never_lower_them(tmp_path):
    cfg = load_config()
    cfg.markets = {
        **cfg.markets,
        "zz": {"label": "Test", "status": "closed",
               "readiness_bars": {"min_grounding_rate": 0.01,   # attempt to lower
                                  "min_discrimination": 0.95}},  # raise
    }
    bars = mk.bars_for(cfg, "zz")
    assert bars["min_grounding_rate"] == mk.DEFAULT_BARS["min_grounding_rate"]
    assert bars["min_discrimination"] == 0.95


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------

def test_fingerprint_changes_when_the_market_config_changes():
    cfg = load_config()
    before = mk.config_fingerprint(cfg, "us")
    cfg.markets = {**cfg.markets,
                   "us": {**cfg.markets["us"], "authority_domains": ["sec.gov"]}}
    assert mk.config_fingerprint(cfg, "us") != before


def test_fingerprint_stable_across_status_flip():
    """Opening a market must not invalidate the readiness fingerprint.

    `status` is operational state, not measurement config. Hashing it made every
    successful `markets open` immediately STALE.
    """
    cfg = load_config()
    cfg.markets = {**cfg.markets,
                   "us": {**cfg.markets["us"], "status": "closed"}}
    before = mk.config_fingerprint(cfg, "us")
    cfg.markets = {**cfg.markets,
                   "us": {**cfg.markets["us"], "status": "open"}}
    assert mk.config_fingerprint(cfg, "us") == before


def test_fingerprint_changes_when_the_bar_changes():
    """A probe measured under different thresholds does not describe this engine."""
    import dataclasses
    cfg = load_config()
    before = mk.config_fingerprint(cfg, "us")
    cfg.thresholds = dataclasses.replace(cfg.thresholds, min_composite_to_pass=4.9)
    assert mk.config_fingerprint(cfg, "us") != before


def test_readiness_round_trips_through_disk(tmp_path):
    cfg = load_config()
    cfg.store["dir"] = str(tmp_path)
    cfg.markets = {**cfg.markets, "us": {**cfg.markets["us"], "readiness_ref": ""}}
    r = mk.evaluate(cfg, "us", _healthy_outcomes())
    path = mk.save_readiness(cfg, r)
    assert path.exists()
    loaded = mk.load_readiness(cfg, "us")
    assert loaded.ready
    assert loaded.config_fingerprint == r.config_fingerprint
    assert loaded.metrics == r.metrics


# ---------------------------------------------------------------------------
# Calibration sets
# ---------------------------------------------------------------------------

def test_shipped_us_calibration_set_is_valid():
    entries = mk.load_calibration_set(CALIBRATION_DIR / "us.jsonl")
    assert len(entries) >= 4
    assert {e["expected"] for e in entries} == {"pass", "kill"}


def test_lane_resolved_fingerprint_differs_from_market_only():
    """`probe --lane` must NOT hash lane gates into READINESS fingerprint.

    show/open load config with no lane pin; a lane-resolved fingerprint would make
    every successful pack probe look STALE. Probe code evaluates fingerprint on
    load_config().for_market(market) only — this test pins why that matters.
    """
    base = load_config().for_market("us")
    lane = base.for_lane("side_hustle")
    assert mk.config_fingerprint(base, "us") != mk.config_fingerprint(lane, "us")
    assert mk.config_fingerprint(base, "us") == mk.config_fingerprint(
        load_config().for_market("us"), "us")


def test_shipped_us_calibration_is_sole_state_pack_shaped():
    """PASS rows are regulator-named packs; KILLs name FinCEN/FCRA/SEC illegality.

    Shape guards the failure mode where a venture-scale idea is judged on the pack
    lane (or vice versa). Does not touch readiness bars.
    """
    entries = mk.load_calibration_set(CALIBRATION_DIR / "us.jsonl")
    passes = [e for e in entries if e["expected"] == "pass"]
    kills = [e for e in entries if e["expected"] == "kill"]
    assert len(passes) >= 2 and len(kills) >= 2
    for e in passes:
        blob = f"{e['title']} {e.get('one_liner', '')}".lower()
        assert "pack" in blob, e["title"]
        assert e.get("ambition_tier") == "side_hustle", e["title"]
    pass_blob = " ".join(f"{e['title']} {e.get('one_liner', '')}".lower() for e in passes)
    # Needles track regulator-named packs that are factually decidable on public
    # US evidence. Do NOT require CSLB CE — California does not mandate contractor CE.
    for needle in ("tdlr", "cosmetology", "2290", "cms", "dme"):
        assert needle in pass_blob, needle
    kill_blob = " ".join(f"{e['title']} {e.get('one_liner', '')}".lower() for e in kills)
    assert "fincen" in kill_blob or "money" in kill_blob
    assert "credit" in kill_blob or "fcra" in kill_blob
    assert "broker" in kill_blob or "sec" in kill_blob


def test_probe_honors_lane_on_calibration_candidates(monkeypatch, tmp_path):
    """`markets probe --lane X` must stamp ambition_tier and vet under for_lane(X)."""
    import argparse
    from types import SimpleNamespace

    from prospector import operator as operator_mod
    from prospector import run as run_mod
    from prospector.models import Decision, Dossier

    cal = tmp_path / "cal.jsonl"
    cal.write_text(
        '{"title": "Pack A", "one_liner": "a pack", "expected": "pass"}\n'
        '{"title": "Illegal B", "one_liner": "bad", "expected": "kill"}\n'
    )
    seen: list[tuple[str, str]] = []

    def _gate_names(cfg) -> set[str]:
        names = set()
        for g in (cfg.hard_gates or []):
            if isinstance(g, dict):
                names.update(g.keys())
            else:
                names.add(str(g))
        return names

    def fake_vet(cand, op, search, cfg, **kwargs):
        seen.append((cand.title, cand.ambition_tier))
        assert "incumbency" not in _gate_names(cfg), cfg.hard_gates
        return Dossier(candidate=cand, decision=Decision.KILL if "Illegal" in cand.title
                       else Decision.PASS, checks=[])

    monkeypatch.setattr(run_mod, "vet_candidate", fake_vet)
    monkeypatch.setattr(operator_mod, "make_operator",
                        lambda *a, **k: SimpleNamespace(name="mock"))
    monkeypatch.setattr(run_mod, "_make_search", lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(run_mod, "_build_config_and_overrides",
                        lambda args: load_config().for_lane(args.lane).for_market(args.market))
    monkeypatch.setattr(run_mod, "Store", lambda cfg: SimpleNamespace())
    from prospector import progress, telemetry
    monkeypatch.setattr(progress, "banner", lambda *a, **k: None)
    monkeypatch.setattr(telemetry, "reset_usage", lambda: None)
    monkeypatch.setattr(mk, "save_readiness",
                        lambda cfg, readiness: tmp_path / "READINESS.json")
    monkeypatch.setattr(mk, "format_readiness", lambda r: "ok")

    args = argparse.Namespace(
        set=str(cal), market="us", lane="side_hustle", probe=False,
        operator=None, fixtures=None, config=None)
    run_mod._run_market_probe(args, load_config(), "us", tmp_path / "log.jsonl")
    assert seen == [("Pack A", "side_hustle"), ("Illegal B", "side_hustle")]


def test_one_sided_calibration_set_is_rejected(tmp_path):
    """A set of only-KILLs is satisfied by an engine that kills everything."""
    p = tmp_path / "bad.jsonl"
    p.write_text('{"title": "a", "expected": "kill"}\n'
                 '{"title": "b", "expected": "kill"}\n')
    with pytest.raises(ValueError, match="no expected-PASS"):
        mk.load_calibration_set(p)


def test_calibration_entry_without_a_known_outcome_is_rejected(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text('{"title": "a", "expected": "maybe"}\n')
    with pytest.raises(ValueError, match="pass.*kill"):
        mk.load_calibration_set(p)


# ---------------------------------------------------------------------------
# Measurement extraction
# ---------------------------------------------------------------------------

def test_outcome_extraction_counts_grounding_and_authority():
    from prospector.retrieval import market_retrieval

    checks = [
        CheckResult(check_name="legality", verdict=Verdict.SUPPORTED, confidence=0.9,
                    rationale="r",
                    sources=[Source.make(url="https://www.sec.gov/x", text="t"),
                             Source.make(url="https://randomblog.example/x", text="t")]),
        CheckResult(check_name="pain_reality", verdict=Verdict.UNVERIFIABLE,
                    confidence=0.1, rationale="r", sources=[]),
    ]
    d = Dossier(candidate=Candidate(title="T", one_liner="O", market="us"),
                decision=Decision.KILL, checks=checks, gate_fired="pain_reality")

    with market_retrieval(load_config().for_market("us")):
        outcome = mk.outcome_from_dossier("kill", d)

    assert outcome.correct
    assert (outcome.grounded_checks, outcome.total_checks) == (1, 2)
    assert (outcome.authority_sources, outcome.total_sources) == (1, 2)


def test_format_readiness_marks_the_failing_bar():
    r = mk.evaluate(load_config(), "us",
                    [_outcome("pass", "pass", auth=0, srcs=10, title="a"),
                     _outcome("kill", "kill", auth=0, srcs=10, title="b")])
    text = mk.format_readiness(r)
    assert "NOT READY" in text
    assert "FAIL" in text
