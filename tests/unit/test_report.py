"""Reporting views over the catalogue + audit log (prospector.report)."""
from __future__ import annotations

import json

from prospector.config import load_config
from prospector.models import Candidate, Decision, Dossier, ScoreResult
from prospector.report import catalogue_report, costs_report, metrics_report
from prospector.store import Store


def _store(tmp_path):
    cfg = load_config()
    cfg.store["dir"] = str(tmp_path)
    return cfg, Store(cfg)


def _pass(title):
    score = ScoreResult(
        scores={ax: 4 for ax in ("pain_acuity", "money_provability", "automatability",
                                 "distribution", "defensibility", "build_feasibility")},
        justification={}, composite=4.0)
    return Dossier(candidate=Candidate(title=title, one_liner="x"),
                   decision=Decision.PASS, score=score, model_version="t", created_at="t")


def _kill(title, gate):
    return Dossier(candidate=Candidate(title=title, one_liner="x"),
                   decision=Decision.KILL, gate_fired=gate, model_version="t", created_at="t")


def test_catalogue_groups_by_decision_pass_first(tmp_path):
    cfg, store = _store(tmp_path)
    store.save(_kill("Dead idea", "value_durability"))
    store.save(_pass("Live idea"))
    out = catalogue_report(store)
    assert "Live idea" in out and "Dead idea" in out
    # PASS section renders before KILL section
    assert out.index("PASS") < out.index("KILL")
    assert "gate=value_durability" in out


def test_catalogue_empty(tmp_path):
    _, store = _store(tmp_path)
    assert "No vetted ideas" in catalogue_report(store)


def test_metrics_kill_rate_and_gate_distribution(tmp_path):
    cfg, store = _store(tmp_path)
    store.save(_kill("a", "value_durability"))
    store.save(_kill("b", "value_durability"))
    store.save(_kill("c", "distribution"))
    store.save(_pass("d"))
    out = metrics_report(store)
    assert "kill rate            75.0%" in out
    assert "value_durability" in out
    # most-killing gate row listed first (match the count-bearing rows, not the
    # word "distribution" in the section header)
    assert out.index("value_durability         2") < out.index("distribution             1")


def test_costs_parses_audit_log(tmp_path):
    log = tmp_path / "prospector.jsonl"
    lines = [
        {"event": "spend", "amount_usd": 0.05, "phase": "signal_pipeline"},
        {"event": "spend", "amount_usd": 0.10, "phase": "signal_pipeline"},
        {"message": "Gemini CLI usage", "web": True, "input": 100, "output": 50, "total": 200},
        {"event": "latency", "operation": "gemini_cli_search", "latency_ms": 5000.0},
    ]
    log.write_text("\n".join(json.dumps(x) for x in lines))
    out = costs_report(log)
    assert "$0.15" in out
    assert "1 web-search" in out
    assert "gemini_cli_search" in out


def test_costs_missing_log(tmp_path):
    assert "No audit log" in costs_report(tmp_path / "nope.jsonl")
