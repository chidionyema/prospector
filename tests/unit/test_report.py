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
    assert "75.0%" in out
    assert "value_durability" in out
    assert "distribution" in out


def test_generation_quality_reads_first_class_structural_form(tmp_path):
    """Regression: structural_form is a first-class field, not tags['form:*'].

    The report once scanned only tags['form:*'] and reported '0 forms' for every
    real run, firing a false 'generator monoculture' alarm while the catalogue was
    in fact structurally diverse. Forms must surface from the canonical field.
    """
    from prospector.report import generation_quality_report
    cfg, store = _store(tmp_path)
    for title, form in [("a", "vertical_saas"), ("b", "local_service"),
                        ("c", "micro_ecommerce")]:
        d = _kill(title, "value_durability")
        d.candidate.structural_form = form
        store.save(d)
    out = generation_quality_report(store)
    assert "3 seen" in out  # all three distinct forms counted
    for form in ("vertical_saas", "local_service", "micro_ecommerce"):
        assert form in out
    assert "0 forms" not in out


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


def test_costs_counts_claude_usage_and_folds_cost(tmp_path):
    log = tmp_path / "prospector.jsonl"
    lines = [
        {"message": "Gemini CLI usage", "web": True, "input": 10, "output": 5, "total": 20},
        {"message": "Claude CLI usage", "web": True, "input": 100, "output": 50,
         "total": 200, "cached": 30, "cost_usd": 0.25},
    ]
    log.write_text("\n".join(json.dumps(x) for x in lines))
    out = costs_report(log)
    assert "2 web-search" in out          # both usage lines counted
    assert "$0.25" in out                 # claude's real billed cost folded into spend


def test_save_removes_stale_decision_file(tmp_path):
    """A re-vet that changes the decision must not leave the old verdict's file."""
    cfg = load_config()
    cfg.store["dir"] = str(tmp_path)
    store = Store(cfg)
    store.save(_kill("Same idea", "incumbency"))
    cid = next(iter(p.name.split(".")[0] for p in (tmp_path / "dossiers").glob("*.json")))
    # re-save the SAME candidate as a PASS
    pass_d = _pass("Same idea")
    pass_d.candidate.candidate_id = cid  # force same id
    store.save(pass_d)
    files = sorted(p.name for p in (tmp_path / "dossiers").glob(f"{cid}.*.json"))
    assert files == [f"{cid}.pass.json"]   # the .kill.json is gone
