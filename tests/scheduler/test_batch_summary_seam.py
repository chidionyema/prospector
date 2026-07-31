"""Integration-seam proof for the batch-summary -> alert wiring.

The cry-wolf bug lived HERE: `_default_generate` summarises a list of real `Dossier` objects into
the `{dossiers, passes, defers}` dict that `alerts_for_tick` classifies. The original code read
`d.verdict` — an attribute `Dossier` does NOT have — so `passes` was structurally always 0 and the
`zero_yield` alert fired on every batch regardless of reality. The earlier "proof" fed synthetic
dicts to the classifier and never exercised this seam with real domain objects, so it could not have
caught the bug. These tests drive the REAL `_default_generate` with REAL `Dossier` objects.
"""
from __future__ import annotations

from prospector.models import Candidate, Decision, Dossier
from prospector.scheduler import run_scheduled as rs


def _dossier(decision: Decision, *, provisional: bool = False) -> Dossier:
    """A real Dossier in a given decision state (only the fields the summary reads matter)."""
    return Dossier(
        candidate=Candidate(title=f"{decision.value} idea"),
        decision=decision, gate_fired=None, reason="", checks=[],
        adversarial=None, score=None, model_version="t", provider_chain="",
        persona="", created_at="2026-06-21T00:00:00Z", reverify_due_at=None,
        provisional=provisional,
    )


def test_real_dossier_has_no_verdict_attr():
    """RED: the assumption the OLD code violated — there is no `.verdict` to read."""
    assert not hasattr(_dossier(Decision.PASS), "verdict")
    assert Decision.PASS.value == "pass"  # the lowercase string the fix counts on


def test_default_generate_counts_real_decisions(monkeypatch):
    """GREEN: a mixed batch of real Dossiers summarises to the correct passes/defers counts."""
    batch = [_dossier(Decision.PASS), _dossier(Decision.KILL),
             _dossier(Decision.DEFER), _dossier(Decision.KILL)]
    # _default_generate does `from prospector.run import run_signal` at call time.
    monkeypatch.setattr("prospector.run.run_signal", lambda *a, **k: batch)

    summary = rs._default_generate(cfg=object(), batch_size=4)

    assert summary == {"dossiers": 4, "passes": 1, "defers": 1, "provisional": 0}


def test_all_deferred_batch_summarises_as_outage(monkeypatch):
    """A moat outage (every candidate DEFERs) must summarise so alerts_for_tick fires moat_deferred."""
    batch = [_dossier(Decision.DEFER) for _ in range(3)]
    monkeypatch.setattr("prospector.run.run_signal", lambda *a, **k: batch)

    summary = rs._default_generate(cfg=object(), batch_size=3)
    assert summary == {"dossiers": 3, "passes": 0, "defers": 3, "provisional": 0}

    from prospector.scheduler.alerts import alerts_for_tick
    specs = alerts_for_tick({"allowed": True, "dry_run": False, "error": None, "result": summary})
    assert specs and specs[0]["key"] == "moat_deferred"  # real seam -> real classification


def test_provisional_batch_summarises_and_alerts_moat_degraded(monkeypatch):
    """A moat DEGRADATION (cheap tail ruled provisionally) must surface + fire CRITICAL.

    This is the silent failure the all-DEFER `moat_deferred` check misses: a provisional batch
    defers NOTHING (it produced rulings), so without counting `provisional` the moat can be down
    for hours with no alert. Drives the REAL seam: provisional Dossiers -> summary -> classifier.
    """
    batch = [_dossier(Decision.PASS, provisional=True),
             _dossier(Decision.KILL, provisional=True),
             _dossier(Decision.KILL, provisional=True)]
    monkeypatch.setattr("prospector.run.run_signal", lambda *a, **k: batch)

    summary = rs._default_generate(cfg=object(), batch_size=3)
    assert summary == {"dossiers": 3, "passes": 1, "defers": 0, "provisional": 3}

    from prospector.scheduler.alerts import alerts_for_tick
    specs = alerts_for_tick({"allowed": True, "dry_run": False, "error": None, "result": summary})
    assert specs and specs[0]["key"] == "moat_provisional"
    assert specs[0]["severity"] == "critical"
    # Degradation must outrank the WARNING zero_yield even when no PASS survives.
    kills_only = [_dossier(Decision.KILL, provisional=True)]
    monkeypatch.setattr("prospector.run.run_signal", lambda *a, **k: kills_only)
    s2 = rs._default_generate(cfg=object(), batch_size=1)
    specs2 = alerts_for_tick({"allowed": True, "dry_run": False, "error": None, "result": s2})
    assert specs2 and specs2[0]["key"] == "moat_provisional"


def test_old_verdict_logic_would_have_miscounted():
    """Document the exact defect: the OLD expression yields 0 even when a PASS is present."""
    batch = [_dossier(Decision.PASS), _dossier(Decision.PASS)]
    old_passes = sum(1 for d in batch if str(getattr(d, "verdict", "")).upper() == "PASS")
    new_passes = sum(1 for d in batch
                     if str(getattr(getattr(d, "decision", None), "value", "")).lower() == "pass")
    assert old_passes == 0   # the cry-wolf bug
    assert new_passes == 2   # the fix
