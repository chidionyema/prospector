"""Batch-level kill-fast on infrastructure.

The defect these pin (2026-08-06, 10:00 UTC batch): 14 candidates vetted end-to-end, 14
defers, zero rulings. The non-critical chain that generates each check's search queries had
been benched by a monthly spend limit, so 52 of 98 checks never produced a query — and a check
with no query has no passages, which `verify.py` reports as `retrieval_failed` -> DEFER_GATE.
Retrieval itself was healthy (200/200 ddg searches `ok`). Nothing counted defers ACROSS
candidates, so candidates 3..14 each re-learned the same outage at full price and every row
landed in a backlog the drain pays for a second time.
"""
from concurrent.futures import Future
from types import SimpleNamespace

from prospector import run as run_mod
from prospector.models import DEFER_GATE


def _dossier(gate):
    return SimpleNamespace(gate_fired=gate)


def _pending(n):
    """n futures that have not started — exactly what `cancel()` is allowed to refuse."""
    return [Future() for _ in range(n)]


# --------------------------------------------------------------------------- streak logic

def test_streak_increments_on_the_defer_gate():
    streak, cancelled = run_mod._infra_abort_check(_dossier(DEFER_GATE), 0, 3, [])
    assert (streak, cancelled) == (1, None)


def test_moat_exhausted_is_also_infrastructure():
    """A blind moat is an outage too — the candidate was never ruled on."""
    streak, cancelled = run_mod._infra_abort_check(_dossier("moat_exhausted"), 1, 3, [])
    assert streak == 2 and cancelled is None


def test_a_real_verdict_RESETS_the_streak():
    """Streak, not total. Two defers either side of a genuine KILL must not trip a 3-threshold."""
    streak = 0
    for gate in (DEFER_GATE, DEFER_GATE, "incumbency", DEFER_GATE, DEFER_GATE):
        streak, cancelled = run_mod._infra_abort_check(_dossier(gate), streak, 3, [])
        assert cancelled is None, f"tripped on {gate!r} — a healthy batch may defer a few"
    assert streak == 2


def test_a_passing_candidate_resets_the_streak():
    streak, cancelled = run_mod._infra_abort_check(_dossier(None), 2, 3, [])
    assert (streak, cancelled) == (0, None)


def test_trips_exactly_AT_the_threshold_not_before():
    pend = _pending(9)
    streak, cancelled = run_mod._infra_abort_check(_dossier(DEFER_GATE), 1, 3, pend)
    assert cancelled is None, "tripped one candidate early"
    streak, cancelled = run_mod._infra_abort_check(_dossier(DEFER_GATE), streak, 3, pend)
    assert (streak, cancelled) == (3, 9)


def test_the_abort_CANCELS_unstarted_vets():
    """The whole point: 12 of 15 candidates never get bought."""
    pend = _pending(12)
    _, cancelled = run_mod._infra_abort_check(_dossier(DEFER_GATE), 2, 3, pend)
    assert cancelled == 12
    assert all(f.cancelled() for f in pend)


def test_it_can_NEVER_discard_work_already_paid_for():
    """`Future.cancel()` refuses a running or finished vet. Evidence bought is evidence kept."""
    running, done = Future(), Future()
    assert running.set_running_or_notify_cancel() is True  # now RUNNING
    done.set_result("a real verdict")
    pend = [running, done, *_pending(4)]
    _, cancelled = run_mod._infra_abort_check(_dossier(DEFER_GATE), 2, 3, pend)
    assert cancelled == 4, "cancelled a vet that was already running or complete"
    assert not running.cancelled() and not done.cancelled()
    assert done.result() == "a real verdict"


def test_threshold_zero_DISABLES_the_breaker():
    pend = _pending(5)
    streak = 0
    for _ in range(20):
        streak, cancelled = run_mod._infra_abort_check(_dossier(DEFER_GATE), streak, 0, pend)
        assert cancelled is None
    assert streak == 20 and not any(f.cancelled() for f in pend)


def test_the_2026_08_06_batch_would_have_stopped_at_3_not_14():
    """Regression on the actual event: 14 consecutive infra defers, batch_size 15."""
    pend = _pending(11)  # 14 submitted, 3 collected by the time the streak trips
    streak, fired_at = 0, None
    for i in range(1, 15):
        streak, cancelled = run_mod._infra_abort_check(_dossier(DEFER_GATE), streak, 3, pend)
        if cancelled is not None and fired_at is None:
            fired_at, n = i, cancelled
            break
    assert fired_at == 3, f"burned {fired_at} candidates before noticing the outage"
    assert n == 11


# --------------------------------------------------------------------------- config wiring

def test_default_streak_is_three():
    cfg = SimpleNamespace(retrieval=SimpleNamespace())
    assert run_mod._infra_abort_streak(cfg) == 3


def test_config_value_is_honoured():
    cfg = SimpleNamespace(retrieval=SimpleNamespace(infra_defer_abort_streak=5))
    assert run_mod._infra_abort_streak(cfg) == 5


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("PROSPECTOR_INFRA_ABORT_STREAK", "1")
    cfg = SimpleNamespace(retrieval=SimpleNamespace(infra_defer_abort_streak=5))
    assert run_mod._infra_abort_streak(cfg) == 1


def test_negative_is_clamped_to_disabled(monkeypatch):
    monkeypatch.setenv("PROSPECTOR_INFRA_ABORT_STREAK", "-4")
    cfg = SimpleNamespace(retrieval=SimpleNamespace())
    assert run_mod._infra_abort_streak(cfg) == 0


# ------------------------------------------------------- the vacuity guard (this session's bug)

def test_the_REAL_config_yaml_parses_and_carries_the_key():
    """Non-vacuous by construction.

    Every other test here builds a SimpleNamespace, so none of them would notice that adding
    `infra_defer_abort_streak` to config.yaml without adding the field to the `Retrieval`
    dataclass makes `load_config()` raise TypeError — which is exactly how the same change
    broke 111 tests earlier today via the `Spend` dataclass. This one calls the real loader.
    """
    from prospector.config import load_config
    cfg = load_config()
    assert hasattr(cfg.retrieval, "infra_defer_abort_streak")
    assert run_mod._infra_abort_streak(cfg) >= 0


# ------------------------------------------- the RAISED outage (the 2026-08-07 daemon-death bug)
#
# `_infra_abort_check` above only ever sees a dossier that was RETURNED. A vet that RAISES
# GroundingInfrastructureError produces no dossier, so before 2026-08-07 it bypassed the streak
# rail entirely: `run.py` re-raised on first sight, `run_scheduled.py:892` caught it and called
# `sys.exit(1)`, and launchd's KeepAlive relaunched. Measured cost in the audit log: 8 distinct
# daemon pids in the 00:00 hour of 2026-08-07 and 7 in the 23:00 hour of 2026-08-06, against a
# ~2.5h tick cadence. These pin the streak-gated replacement.

def test_a_single_raised_outage_does_not_halt():
    """THE regression. One unlucky tail query must not kill the daemon."""
    assert run_mod._infra_exception_action(1, 3) == "continue"


def test_second_consecutive_raised_outage_still_does_not_halt():
    assert run_mod._infra_exception_action(2, 3) == "continue"


def test_third_consecutive_raised_outage_halts():
    """A SUSTAINED outage must still stop the daemon — the spend rail is not being removed."""
    assert run_mod._infra_exception_action(3, 3) == "halt"


def test_streak_beyond_threshold_stays_halt():
    assert run_mod._infra_exception_action(9, 3) == "halt"


def test_threshold_of_one_halts_immediately():
    """threshold=1 reproduces the old behaviour exactly, for an operator who wants it."""
    assert run_mod._infra_exception_action(1, 1) == "halt"


def test_disabled_rail_preserves_the_old_immediate_raise():
    """threshold 0 disables the streak rail. It must fall back to the pre-2026-08-07 halt,
    NOT to swallowing every outage — disabling a brake must never be quieter than having none."""
    for streak in (1, 2, 3, 50):
        assert run_mod._infra_exception_action(streak, 0) == "raise"


def test_raised_and_returned_outages_share_one_streak():
    """A batch that defers twice on DEFER_GATE and THEN raises has seen three consecutive
    'cannot rule' events, so the third must trip. If the two paths kept separate counters an
    alternating outage would never reach any threshold."""
    streak = 0
    for gate in (DEFER_GATE, DEFER_GATE):
        streak, cancelled = run_mod._infra_abort_check(_dossier(gate), streak, 3, [])
        assert cancelled is None
    streak += 1  # the raise, counted into the SAME streak by run_signal
    assert run_mod._infra_exception_action(streak, 3) == "halt"


def test_a_healthy_verdict_resets_the_streak_before_a_raise():
    """Two outages, one clean ruling, one outage = not sustained. Must not halt."""
    streak = 0
    for gate in (DEFER_GATE, DEFER_GATE):
        streak, _ = run_mod._infra_abort_check(_dossier(gate), streak, 3, [])
    streak, _ = run_mod._infra_abort_check(_dossier(None), streak, 3, [])
    assert streak == 0, "a grounded ruling must reset the consecutive counter"
    streak += 1
    assert run_mod._infra_exception_action(streak, 3) == "continue"


def test_infra_gates_are_only_non_verdict_gates():
    """Guard against a grounded gate (e.g. 'incumbency') ever being treated as an outage —
    that would let a run of legitimately-killed candidates abort a perfectly healthy batch."""
    assert DEFER_GATE in run_mod._INFRA_GATES
    for real_gate in ("incumbency", "pain_reality", "min_composite", "legality"):
        assert real_gate not in run_mod._INFRA_GATES
