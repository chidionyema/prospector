"""Each half of the split can be stopped without stopping the other — and PAUSE still stops both.

THE SHAPE BEING PINNED (three files, three scopes):

    store/scheduler/PAUSE             -> BOTH roles. The liability rail.
    store/scheduler/PAUSE_GENERATION  -> the PRODUCER only; the drain keeps working.
    store/scheduler/PAUSE_CONSUMER    -> the CONSUMER only; generation keeps filling the queue.

WHY THE THIRD ONE HAD TO EXIST. The producer has had a half-stop since the split's first rule.
The consumer had none, so "hold the drain for an hour while I look at the moat" could only be
expressed by touching PAUSE — the liability rail — for a routine reason. That is how a
liability rail ends up switched on for a week: the operator reaches for it for something small,
and nothing about the small thing reminds them to switch it back.

WHY THE ASYMMETRY IS TESTED IN BOTH DIRECTIONS. A half-stop that quietly stopped both halves
would look exactly like a working one from the side you were watching. The only way to catch it
is to assert on the half you did NOT stop.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

from prospector import consumer as consumer_mod


def _cfg(tmp_path):
    return types.SimpleNamespace(store_dir=str(tmp_path), schedule={}, spend={})


def _sched_dir(tmp_path) -> Path:
    d = tmp_path / "scheduler"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _allow_guard(monkeypatch, allowed=True, reason="daily spend cap reached"):
    """Pin the SHARED rail so these tests measure the per-role one and nothing else."""
    calls: list[int] = []

    def fake(_cfg):
        calls.append(1)
        return (allowed, None if allowed else reason)

    monkeypatch.setattr("prospector.scheduler.guard.guard_check", fake)
    return calls


# ---------------------------------------------------------------------------
# The consumer's own half-stop
# ---------------------------------------------------------------------------

def test_pause_consumer_blocks_the_consumer(monkeypatch, tmp_path):
    _allow_guard(monkeypatch)
    (_sched_dir(tmp_path) / consumer_mod.CONSUMER_PAUSE_FILENAME).touch()

    reason = consumer_mod._blocked_reason(_cfg(tmp_path))

    assert reason and consumer_mod.CONSUMER_PAUSE_FILENAME in reason


def test_no_pause_file_means_the_consumer_runs(monkeypatch, tmp_path):
    """The negative control. Without it this file would pass on a `_blocked_reason` that
    refused everything."""
    _allow_guard(monkeypatch)
    _sched_dir(tmp_path)

    assert consumer_mod._blocked_reason(_cfg(tmp_path)) is None


def test_the_half_stop_is_checked_before_the_spend_ledger_scan(monkeypatch, tmp_path):
    """Not a micro-optimisation: `guard_check` re-scans store/prospector.jsonl, measured at
    108s on a 157 MB one. An operator who has explicitly stopped the consumer must not pay two
    minutes of I/O per cycle to be told what they already know."""
    calls = _allow_guard(monkeypatch)
    (_sched_dir(tmp_path) / consumer_mod.CONSUMER_PAUSE_FILENAME).touch()

    consumer_mod._blocked_reason(_cfg(tmp_path))

    assert calls == [], "the pause check must short-circuit before the guard evaluates"


def test_the_shared_liability_rail_still_stops_the_consumer(monkeypatch, tmp_path):
    """PAUSE and the spend cap reach the consumer through `guard_check` — the daemon's OWN
    function, so the two processes can never disagree about whether spending is allowed."""
    _allow_guard(monkeypatch, allowed=False)
    _sched_dir(tmp_path)

    assert consumer_mod._blocked_reason(_cfg(tmp_path)) == "daily spend cap reached"


def test_an_unreadable_store_does_not_block_on_the_pause_check_alone(monkeypatch, tmp_path):
    """The pause probe must fail OPEN, because the guard below it is the rail that is allowed
    to stop the loop — and it stops it with a reason. A probe that failed closed would halt the
    drain on a transient stat() error and report it as an operator pause."""
    _allow_guard(monkeypatch)
    monkeypatch.setattr("prospector.scheduler.paths.scheduler_dir",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("gone")))

    assert consumer_mod._blocked_reason(_cfg(tmp_path)) is None


# ---------------------------------------------------------------------------
# The asymmetry: each half-stop moves its own half only
# ---------------------------------------------------------------------------

def test_pausing_generation_does_not_stop_the_consumer(monkeypatch, tmp_path):
    """The producer's half-stop exists precisely so the drain keeps working. If it reached the
    consumer, PAUSE_GENERATION would silently be a second PAUSE."""
    from prospector.scheduler import run_scheduled

    _allow_guard(monkeypatch)
    (_sched_dir(tmp_path) / run_scheduled._GENERATION_PAUSE_FILENAME).touch()

    assert consumer_mod._blocked_reason(_cfg(tmp_path)) is None


def test_pausing_the_consumer_does_not_stop_generation(monkeypatch, tmp_path):  # noqa: PLR0913
    """And the mirror image: the producer must keep filling the queue while vetting is held."""
    from prospector.scheduler import run_scheduled

    (_sched_dir(tmp_path) / consumer_mod.CONSUMER_PAUSE_FILENAME).touch()
    # `_generation_suppressed` also consults grounding and the backlog cap; pin both so this
    # measures the pause file and not the state of the world.
    monkeypatch.setattr(run_scheduled, "_grounding_degraded_reason", lambda *a, **k: "")
    monkeypatch.setattr(run_scheduled, "_subscription_soft_cap_reason", lambda *a, **k: "")
    monkeypatch.setattr(run_scheduled, "_backlog_brake_reason", lambda *a, **k: "", raising=False)

    assert run_scheduled._generation_suppressed(_cfg(tmp_path)) == ""


def test_the_three_pause_filenames_are_distinct():
    """A collision is invisible: both rails would still 'work', and the only symptom would be
    one half mysteriously stopping with the other."""
    from prospector.scheduler import run_scheduled
    from prospector.scheduler.guard import PAUSE_FILENAME

    names = {PAUSE_FILENAME, run_scheduled._GENERATION_PAUSE_FILENAME,
             consumer_mod.CONSUMER_PAUSE_FILENAME}
    assert len(names) == 3


# ---------------------------------------------------------------------------
# The two launchd roles
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("plist,label", [
    ("com.prospector.scheduler.plist", "com.prospector.scheduler"),
    ("com.prospector.consumer.plist", "com.prospector.consumer"),
])
def test_both_roles_ship_a_plist_with_its_own_label(plist, label):
    text = (REPO / "deploy" / plist).read_text()
    assert f"<string>{label}</string>" in text


def test_the_two_roles_do_not_share_a_log_file():
    """Two resident processes appending to one file interleave mid-line, and the first thing
    anyone does with these logs is attribute a failure to a phase — which is exactly what
    interleaving destroys."""
    import plistlib

    def _paths(name):
        d = plistlib.loads((REPO / "deploy" / name).read_bytes())
        return {d["StandardOutPath"], d["StandardErrorPath"]}

    assert not _paths("com.prospector.scheduler.plist") & _paths("com.prospector.consumer.plist")


def test_the_consumer_plist_invokes_the_consumer_command():
    """Pinned because a plist is not exercised by any other test and fails silently in launchd:
    a wrong subcommand shows up as a job that respawns forever and does nothing."""
    import plistlib

    argv = plistlib.loads(
        (REPO / "deploy" / "com.prospector.consumer.plist").read_bytes())["ProgramArguments"]

    assert argv[1:3] == ["-m", "prospector.run"]
    assert "consume" in argv
    assert "--publish" in argv, "the consumer owns publishing; without this nothing ever lists"
    # `--config` is a TOP-LEVEL option: argparse does not hand an unknown option back up from a
    # subparser, so after `consume` it is an exit-2 usage error — which under KeepAlive is a
    # respawn every 120s and no work, forever.
    assert argv.index("--config") < argv.index("consume")


def test_the_consumer_argv_actually_parses(monkeypatch, tmp_path):
    """A plist is exercised by nothing else, and launchd reports a usage error as a job that
    respawns every 120s and does nothing. So run the REAL argv through the REAL parser
    (`run.main`, with the command stubbed) rather than eyeballing the strings above.

    Fails loudly on the `--config`-after-subcommand mistake: argparse exits 2, which surfaces
    here as SystemExit instead of the stub being reached.
    """
    import plistlib
    import sys

    from prospector import run as run_mod

    argv = plistlib.loads(
        (REPO / "deploy" / "com.prospector.consumer.plist").read_bytes())["ProgramArguments"]
    # Drop the interpreter, `-m` and the module name — everything the shell strips itself.
    args = argv[3:]

    seen: dict = {}
    monkeypatch.setattr(run_mod, "_cmd_consume",
                        lambda a, **kw: seen.update(publish=a.publish) or 0)
    # `main()` routes logs before dispatching, so the stub config needs a real store_dir —
    # and it must be tmp_path, never the live store (CLAUDE.md: tests never write there).
    monkeypatch.setattr(run_mod, "load_config",
                        lambda *a, **k: types.SimpleNamespace(store_dir=tmp_path))
    monkeypatch.setattr(sys, "argv", ["prospector.run", *args])

    try:
        run_mod.main()
    except SystemExit as e:  # argparse usage error, or a clean exit(0)
        assert e.code in (0, None), f"the plist's argv does not parse (exit {e.code})"

    assert seen.get("publish") is True, "the consumer must be invoked with publishing on"
