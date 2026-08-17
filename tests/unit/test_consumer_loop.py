"""The consumer: a vetting loop whose stop conditions are all RETRYABLE.

Every reason a drain pass cannot run right now — PAUSE, the daily cap, a benched moat, an
empty queue — is transient, so each one is a WAIT here rather than an exit.

Not because exiting would break the split: it would not. The durable queue is what decouples
the halves, and a consumer that exits on PAUSE and is restarted by a supervisor leaves the
producer just as unblocked and the rows just as safe (`consume --once` is exactly that, and
is supported). The reason is cost and legibility — a restart re-pays config load,
`make_operator`'s network calls and a guard evaluation that re-scans the spend ledger, and a
process respawning every cycle reads as a crash loop.

So these tests are mostly about not-dying, and about the loop keeping the rails it inherited
rather than earning an exception because it is long-lived. `sleep` is injected throughout: a
test that expected a backoff and got none would otherwise hang for 60s and pass by timeout.
"""
from __future__ import annotations

import types

import pytest

from prospector import consumer as C


class _Sleeps(list):
    """Records the pacing instead of taking it. The DURATIONS are asserted on, because
    "blocked" and "idle" are told apart by which backoff was taken and nothing else."""

    def __call__(self, s):
        self.append(s)


def _cfg(**consumer_block):
    return types.SimpleNamespace(consumer=consumer_block or {})


def _drain(monkeypatch, *returns):
    """Stub `resume_deferred` with a scripted sequence of pass results."""
    seq = list(returns)
    calls: list = []

    def _fake(cfg, *, limit=None, publish=False, **kw):
        calls.append({"limit": limit, "publish": publish})
        out = seq.pop(0) if seq else {"attempted": 0, "resumed": 0}
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr("prospector.run.resume_deferred", _fake)
    return calls


def _allow(monkeypatch, allowed=True, reason="ok"):
    monkeypatch.setattr("prospector.scheduler.guard.guard_check",
                        lambda cfg: (allowed, reason))


# --------------------------------------------------------------------------- #
# 1. It drains
# --------------------------------------------------------------------------- #
def test_it_drains_until_max_passes(monkeypatch):
    _allow(monkeypatch)
    calls = _drain(monkeypatch, {"attempted": 5, "resumed": 5}, {"attempted": 5, "resumed": 4})
    sleeps = _Sleeps()

    out = C.run_consumer(_cfg(batch=5), max_passes=2, sleep=sleeps)

    assert out["passes"] == 2
    assert out["resumed"] == 9, "the summary is CUMULATIVE, not the last pass"
    assert out["attempted"] == 10
    assert [c["limit"] for c in calls] == [5, 5]
    assert out["stopped_because"] == "max_passes=2"


def test_the_summary_is_cumulative_not_the_final_pass(monkeypatch):
    """A healthy run ends on an empty queue. Reporting only the last cycle would show
    `resumed: 0` for every successful consumer — indistinguishable from one that never
    worked."""
    _allow(monkeypatch)
    _drain(monkeypatch, {"attempted": 3, "resumed": 3}, {"attempted": 0, "resumed": 0})
    sleeps = _Sleeps()

    out = C.run_consumer(_cfg(), max_passes=2, sleep=sleeps)

    assert out["resumed"] == 3 and out["idle"] == 1


# --------------------------------------------------------------------------- #
# 2. Every stop condition is a WAIT, never an exit
# --------------------------------------------------------------------------- #
def test_pause_blocks_the_loop_without_ending_it(monkeypatch):
    """CLAUDE.md: PAUSE halts the ENTIRE tick, "a rail with exceptions is not a rail" — and a
    long-lived consumer is exactly the process a tempting exception gets written for. It must
    also RESUME by itself: an operator who removes the file expects work, not a restart."""
    state = {"paused": True}
    monkeypatch.setattr("prospector.scheduler.guard.guard_check",
                        lambda cfg: (not state["paused"], "paused: PAUSE present"))
    _drain(monkeypatch, {"attempted": 2, "resumed": 2})
    sleeps = _Sleeps()

    def _unpause_after_first_wait(s):
        sleeps.append(s)
        state["paused"] = False

    out = C.run_consumer(_cfg(blocked_s=300), max_passes=1, sleep=_unpause_after_first_wait)

    assert out["blocked"] == 1, "the paused cycle is counted, not silent"
    assert sleeps[0] == 300, "a block takes the LONG backoff"
    assert out["passes"] == 1 and out["resumed"] == 2, "and it resumed by itself"


def test_the_spend_cap_blocks_it_through_the_daemons_own_guard(monkeypatch):
    """Not a second implementation. `guard_check` is the daemon's function, so the two
    processes cannot disagree about whether spending is allowed — which they would, silently,
    on the day one of them learned about a new cap."""
    seen: list = []
    monkeypatch.setattr("prospector.scheduler.guard.guard_check",
                        lambda cfg: seen.append(cfg) or (False, "daily cap reached: $20 >= $20"))
    _drain(monkeypatch)
    sleeps = _Sleeps()

    out = C.run_consumer(_cfg(), max_passes=1, sleep=sleeps)

    assert seen, "the guard was consulted"
    assert out["blocked"] >= 1 and out["passes"] == 0, "no pass ran over the cap"


def test_an_unreadable_guard_stops_it_rather_than_spending(monkeypatch):
    """A rail that cannot be evaluated is not permission to spend — CLAUDE.md forbids
    unattended running without the two rails. It blocks (retryable) rather than raising,
    because the usual cause is the ledger being rewritten underneath the read."""
    monkeypatch.setattr("prospector.scheduler.guard.guard_check",
                        lambda cfg: (_ for _ in ()).throw(OSError("ledger truncated")))
    calls = _drain(monkeypatch)
    sleeps = _Sleeps()

    out = C.run_consumer(_cfg(), max_passes=1, sleep=sleeps)

    assert calls == [], "no drain pass may run on an unevaluated rail"
    assert out["blocked"] >= 1


def test_a_blind_moat_is_a_backoff_not_an_exit(monkeypatch):
    """The single most important property of the whole split. Under a tick, a moat outage
    meant the vetting third of every tick did nothing until a human noticed. The consumer's
    job is to be ALIVE when the brain returns, so the queue drains itself the moment it does.

    `skipped` is `_cmd_resume`'s own refusal — the preflight is not duplicated here."""
    _allow(monkeypatch)
    _drain(monkeypatch,
           {"attempted": 0, "resumed": 0, "skipped": "moat blind: claude_cli dead for 3033s"},
           {"attempted": 4, "resumed": 4})
    sleeps = _Sleeps()

    out = C.run_consumer(_cfg(blocked_s=300, idle_s=60), max_passes=2, sleep=sleeps)

    assert out["blocked"] == 1
    assert sleeps[0] == 300, "a refused pass waits the BLOCKED backoff, not the idle one"
    assert out["idle"] == 0, "a refused pass is not an empty queue — the rows are still there"
    assert out["resumed"] == 4, "and it drained as soon as the moat returned"


def test_one_failed_pass_does_not_end_the_consumer(monkeypatch):
    """Exiting on an exception hands the queue back to whatever restarts the process. The
    point of a long-running consumer is that it is still there when the transient thing ends."""
    _allow(monkeypatch)
    _drain(monkeypatch, RuntimeError("adapter crashed"), {"attempted": 2, "resumed": 2})
    sleeps = _Sleeps()

    out = C.run_consumer(_cfg(), max_passes=2, sleep=sleeps)

    assert out["errors"] == 1
    assert out["resumed"] == 2, "the next pass ran normally"


def test_an_empty_queue_is_an_idle_wait_not_a_block(monkeypatch):
    """Told apart by the backoff taken. Conflating them would either make an empty queue poll
    a spend-ledger scan every cycle, or make a capped consumer hammer the store every minute."""
    _allow(monkeypatch)
    _drain(monkeypatch, {"attempted": 0, "resumed": 0})
    sleeps = _Sleeps()

    out = C.run_consumer(_cfg(idle_s=60, blocked_s=300), max_passes=1, sleep=sleeps)

    assert out["idle"] == 1 and out["blocked"] == 0
    assert sleeps == [60]


# --------------------------------------------------------------------------- #
# 3. Stopping cleanly
# --------------------------------------------------------------------------- #
def test_a_stop_signal_finishes_the_pass_it_is_in(monkeypatch):
    """SIGKILL mid-vet is survivable — the lease expires and the row returns — but not free:
    the partial vet is paid for and thrown away, and the row is invisible for lease_ttl_s
    (7200s) before anyone can retake it. A cooperative stop costs one more pass and no rows."""
    _allow(monkeypatch)
    flag = C.StopFlag()
    passes = {"n": 0}

    def _fake(cfg, *, limit=None, publish=False, **kw):
        passes["n"] += 1
        flag.stop("SIGTERM")           # arrives mid-pass
        return {"attempted": 3, "resumed": 3}

    monkeypatch.setattr("prospector.run.resume_deferred", _fake)
    out = C.run_consumer(_cfg(), stop=flag, sleep=_Sleeps())

    assert passes["n"] == 1, "the in-flight pass completed; no second pass started"
    assert out["resumed"] == 3, "its rows were banked, not abandoned"
    assert out["stopped_because"] == "SIGTERM"


def test_the_stop_flag_never_unsets_itself():
    """Two rapid signals must not race, and the second one is usually the operator wondering
    why the first did nothing."""
    flag = C.StopFlag()
    flag.stop("SIGTERM")
    flag.stop("SIGINT")
    assert flag.stopped and flag.reason == "SIGTERM", "the FIRST reason is the true one"


def test_a_stopped_flag_means_no_pass_runs_at_all(monkeypatch):
    _allow(monkeypatch)
    calls = _drain(monkeypatch, {"attempted": 9, "resumed": 9})
    flag = C.StopFlag()
    flag.stop("already stopping")

    out = C.run_consumer(_cfg(), stop=flag, sleep=_Sleeps())
    assert calls == [] and out["passes"] == 0


# --------------------------------------------------------------------------- #
# 4. Config
# --------------------------------------------------------------------------- #
def test_the_pacing_is_read_from_the_live_config():
    """Not just declared in config.yaml — READ from it. A config knob nobody reads is the
    defect class that made `candidates_per_signal: 50` mean 5 for as long as the line existed."""
    from pathlib import Path

    import yaml

    from prospector.config import load_config

    # Compare against what config.yaml SAYS, not against a literal. The literal pinned the
    # tuning value: raising `batch` 5 -> 24 on 2026-08-16 (three idle worker slots per wave,
    # measured 1.54 rows in flight against 8) failed this test, which is the knob being tuned
    # working exactly as intended. What must never regress is that the loop READS the file.
    raw = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "config.yaml").read_text()
    )["consumer"]
    conf = C.consumer_config(load_config())
    assert conf.batch == raw["batch"]
    assert conf.idle_s == float(raw["idle_s"])
    assert conf.blocked_s == float(raw["blocked_s"])
    # And it must be a real read, not a default that happens to match: the dataclass default
    # is 5, so a `batch` that equals the default proves nothing about the file being read.
    assert raw["batch"] != C.ConsumerConfig.batch


def test_a_missing_consumer_block_runs_at_defaults():
    """A loop that crashes on an absent config block cannot be introduced to a running estate:
    the config change and the code change would have to land in the same instant."""
    conf = C.consumer_config(types.SimpleNamespace())
    assert conf.batch == 5 and conf.idle_s == 60.0


@pytest.mark.parametrize("bad", [0, -1, "loads", None])
def test_a_nonsense_batch_falls_back_rather_than_no_opping(bad):
    """batch<=0 makes every pass a no-op that still pays full operator construction — a
    consumer that reads as wedged and is really a typo."""
    assert C.consumer_config(_cfg(batch=bad)).batch >= 1


@pytest.mark.parametrize("bad", [-5, "soon"])
def test_a_nonsense_backoff_never_spins(bad):
    conf = C.consumer_config(_cfg(idle_s=bad, blocked_s=bad))
    assert conf.idle_s >= 0 and conf.blocked_s >= 0


# --------------------------------------------------------------------------- #
# 5. It is not a second drain
# --------------------------------------------------------------------------- #
def test_the_consumer_delegates_to_the_one_drain_implementation():
    """A duplicated drain is the defect shape `errors.looks_exhausted` exists to prevent: two
    copies drift, and the one that drifts is the one nobody watches. The lease, the moat
    preflight, the trusted-only classifier and the exclusions all live in `_cmd_resume`, and
    the consumer must own NONE of them.

    Checked on identifiers in the source rather than on prose — a docstring search for "lease"
    matches the word "releases" and would pass on a module that had never heard of one."""
    import inspect

    src = inspect.getsource(C)
    assert "resume_deferred" in src, "it must call the real drain"
    for owned_elsewhere in ("moat_blind_reason", "drainable(", ".claim(", "ThreadPoolExecutor",
                            "vet_candidate"):
        assert owned_elsewhere not in src, (
            f"{owned_elsewhere} is the drain's job; a second copy here would drift")


def test_publish_is_passed_through_not_reinvented(monkeypatch):
    """The consumer is where PASSes now reach the money rail, so the flag must arrive at the
    drain untouched rather than being re-derived from anything local."""
    _allow(monkeypatch)
    calls = _drain(monkeypatch, {"attempted": 1, "resumed": 1})

    C.run_consumer(_cfg(), max_passes=1, publish=True, sleep=_Sleeps())

    assert calls[0]["publish"] is True
