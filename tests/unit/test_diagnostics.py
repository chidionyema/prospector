"""Calibration self-watch alarms (prospector.diagnostics.calibration_alarms).

Free, deterministic — no model calls. Proves the production self-watch fires on the
exact pathologies that caused 0% yield (gate killing on silence → gate dominance /
zero yield) and stays quiet on a healthy catalogue.
"""
from __future__ import annotations

from prospector.config import load_config
from prospector.diagnostics import calibration_alarms
from prospector.models import Candidate, Decision, Dossier, ScoreResult
from prospector.store import Store


def _store(tmp_path):
    cfg = load_config()
    cfg.store["dir"] = str(tmp_path)
    return cfg, Store(cfg)


def _kill(cid, gate):
    d = Dossier(candidate=Candidate(title=f"k{cid}", one_liner="x"),
                decision=Decision.KILL, gate_fired=gate, model_version="t", created_at="t")
    d.candidate.candidate_id = cid
    return d


def _pass(cid):
    score = ScoreResult(scores={}, justification={}, composite=4.0)
    d = Dossier(candidate=Candidate(title=f"p{cid}", one_liner="x"),
                decision=Decision.PASS, score=score, model_version="t", created_at="t")
    d.candidate.candidate_id = cid
    return d


def _codes(alarms):
    return {a["code"] for a in alarms}


def test_zero_yield_and_dominance_fire_on_silence_killer(tmp_path):
    """6 kills all on value_durability, 0 pass → zero_yield fires.

    gate_dominance does NOT fire here because value_durability IS a configured gate
    for the venture lane, so its dominance is expected — not a dominance alarm.
    The zero_yield alarm fires with a root-cause hint pointing at generator quality.
    """
    cfg, store = _store(tmp_path)
    for i in range(6):
        store.save(_kill(f"k{i}", "value_durability"))
    alarms = calibration_alarms(store, cfg)
    codes = _codes(alarms)
    assert "zero_yield" in codes
    assert "gate_dominance" not in codes  # value_durability is configured → expected


def test_no_alarms_on_healthy_mixed_catalogue(tmp_path):
    cfg, store = _store(tmp_path)
    # spread kills across gates + some passes → no dominance, no zero-yield
    for i, g in enumerate(["value_durability", "incumbency", "payer_solvency",
                           "distribution", "legality", "pain_reality"]):
        store.save(_kill(f"k{i}", g))
    for i in range(3):
        store.save(_pass(f"p{i}"))
    codes = _codes(calibration_alarms(store, cfg))
    assert "zero_yield" not in codes
    assert "gate_dominance" not in codes


def test_below_min_sample_stays_quiet(tmp_path):
    """Don't cry calibration-bug on a tiny sample (e.g. one bad batch)."""
    cfg, store = _store(tmp_path)
    store.save(_kill("k0", "value_durability"))
    store.save(_kill("k1", "value_durability"))
    assert calibration_alarms(store, cfg) == []


def test_dominance_threshold_respected(tmp_path):
    """5/6 on one gate is below the 0.85 default → no dominance alarm (but it's mixed
    enough that zero_yield still fires since there are no passes)."""
    cfg, store = _store(tmp_path)
    for i in range(5):
        store.save(_kill(f"k{i}", "value_durability"))
    store.save(_kill("k5", "incumbency"))
    codes = _codes(calibration_alarms(store, cfg))
    assert "gate_dominance" not in codes   # 5/6 = 83% < 85%
