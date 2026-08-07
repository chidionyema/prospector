"""Integration: soft early-exit in verify() — DEFER-safe, instrumented, same gates."""
from __future__ import annotations

from prospector.config import load_config
from prospector.models import DEFER_GATE, Candidate
from prospector.operator import MockOperator
from prospector.pass_ceiling import SOFT_EXIT_GATES
from prospector.retrieval import SearchProvider
from prospector.verify import verify


class _EmptyProvider(SearchProvider):
    def search(self, query: str, k: int = 4, max_chars: int = 1500):
        return []


class _FailingProvider(SearchProvider):
    def search(self, query: str, k: int = 4, max_chars: int = 1500):
        raise RuntimeError("simulated infra outage")


def _side_hustle_cfg():
    cfg = load_config()
    cfg.retrieval.cache = False
    cfg.retrieval.queries_per_check = 1
    cfg.retrieval.fast_queries = 1
    return cfg.for_lane("side_hustle")


def _cand() -> Candidate:
    return Candidate(
        title="Test Pack",
        one_liner="A test idea",
        why_now="now",
        structural_form="info_product",
    )


def test_soft_exit_skips_score_checks_when_moat_floor_impossible():
    """After hard gates finish, moat_ungrounded may skip score_checks."""
    cfg = _side_hustle_cfg()
    assert cfg.lanes["side_hustle"].get("score_checks")
    op = MockOperator()
    cand = _cand()
    checks, adv, gate = verify(op, _EmptyProvider(), cfg, cand, skip_adversarial=True)
    hard = set(cfg.gate_map())
    score_checks = set(cfg.lanes["side_hustle"].get("score_checks") or [])
    # Soft-exit path: PASS floors impossible after hard gates → skip score_checks.
    assert gate in SOFT_EXIT_GATES
    assert gate not in hard
    assert adv is None
    run_names = {c.check_name for c in checks}
    # Must have run hard gates; must not have run score-only extras.
    assert hard.issubset(run_names) or run_names.issubset(hard | score_checks)
    assert not (run_names & (score_checks - hard)), (
        f"score_checks should be skipped on soft exit, ran {run_names & score_checks}")
    tp = cand.tags["verify_throughput"]
    assert tp["checks_run"] == len(checks)
    assert tp["checks_skipped_soft_exit"] >= 1
    assert tp["soft_exit_gate"] == gate


def test_soft_exit_does_not_override_defer_on_retrieval_failure():
    cfg = _side_hustle_cfg()
    op = MockOperator()
    cand = _cand()
    checks, adv, gate = verify(op, _FailingProvider(), cfg, cand, skip_adversarial=True)
    assert gate == DEFER_GATE
    assert any(getattr(c, "retrieval_failed", False) for c in checks)
    assert "verify_throughput" not in cand.tags


def test_full_vet_runs_score_checks_despite_impossible_pass():
    cfg = _side_hustle_cfg()
    op = MockOperator()
    cand = _cand()
    checks, adv, gate = verify(
        op, _EmptyProvider(), cfg, cand, skip_adversarial=True, full_vet=True)
    score_checks = cfg.lanes["side_hustle"].get("score_checks") or []
    gated = [k for g in cfg.hard_gates for k in g if k != "adversarial_decisive"]
    expected_extras = [c for c in score_checks if c not in gated]
    expected = len(gated) + len(expected_extras)
    assert len(checks) == expected
    assert "verify_throughput" not in cand.tags


def test_silence_soft_exit_skips_adversarial_when_pass_impossible():
    cfg = _side_hustle_cfg()
    op = MockOperator()
    cand = _cand()
    checks, adv, gate = verify(op, _EmptyProvider(), cfg, cand, skip_adversarial=False)
    assert gate in SOFT_EXIT_GATES
    assert adv is None
    tp = cand.tags["verify_throughput"]
    assert tp["checks_run"] == len(checks)
    assert tp["soft_exit_gate"] == gate
