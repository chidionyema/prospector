"""Proofs for the shared Claude usage-wall marker and the two rails that read it.

No network, no CLI, no wall clock: every test drives an explicit `now` and an env-overridden
marker path. That is deliberate — the thing under test is a rail that decides whether to spend
money, and a rail proven only by a live outage is a rail proven once a month.

The tests are written as falsifiers where a falsifier exists. It is easy to write a test that
passes because the code never runs (see the 2026-08-06 "verified by reading only the edited
file" defect), so each blocking test has a matching non-blocking twin.
"""
from __future__ import annotations

import importlib.util
import json
import os
import types
from pathlib import Path

import pytest

from prospector import usage_wall
from prospector.errors import ProviderExhaustedError

NOW = 1_800_000_000.0


@pytest.fixture(autouse=True)
def marker(tmp_path, monkeypatch):
    """Point the module at a throwaway marker. Without this a test would read — and WRITE —
    the estate's real marker and could bench both live daemons."""
    p = tmp_path / "state" / "claude_usage_limit.json"
    monkeypatch.setenv("PROSPECTOR_USAGE_WALL_MARKER", str(p))
    return p


def _write(path: Path, **fields) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fields), encoding="utf-8")


# --------------------------------------------------------------------------- read()

def test_absent_marker_is_not_a_wall(marker):
    assert not marker.exists()
    assert usage_wall.read(now=NOW) is None
    assert usage_wall.is_blocked(now=NOW) is False
    assert usage_wall.reason(now=NOW) == ""


def test_live_marker_is_a_wall(marker):
    _write(marker, reset_at=NOW + 600, observed_at=NOW, observed_by="otto-coordinator",
           source="Claude AI usage limit reached")
    assert usage_wall.is_blocked(now=NOW) is True
    assert usage_wall.blocked_for(now=NOW) == pytest.approx(600)
    r = usage_wall.reason(now=NOW)
    assert "otto-coordinator" in r and "usage" in r.lower()


def test_expired_marker_is_not_a_wall(marker):
    """The FALSIFIER for the test above: same file, reset in the past, must not block."""
    _write(marker, reset_at=NOW - 1, observed_at=NOW - 600, observed_by="otto-coordinator")
    assert usage_wall.read(now=NOW) is None
    assert usage_wall.is_blocked(now=NOW) is False


@pytest.mark.parametrize("body", [
    "not json at all",
    json.dumps([1, 2, 3]),                       # valid JSON, wrong shape
    json.dumps({"reset_at": "tomorrow"}),        # unparseable epoch
    json.dumps({"observed_by": "otto"}),         # no reset_at
])
def test_malformed_marker_fails_open(marker, body):
    """FAIL OPEN. A reader bug must not stall the daemon: worse than the hammering it prevents."""
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(body, encoding="utf-8")
    assert usage_wall.read(now=NOW) is None
    assert usage_wall.is_blocked(now=NOW) is False


def test_millisecond_epoch_in_marker_is_treated_as_corrupt_not_clamped(marker, caplog):
    """The ms-as-seconds trap. `reset_at` has appeared as ms; read as seconds it lands in the
    year 58000. Clamping would still bench the daemon for the maximum window, so an implausible
    value must be IGNORED — and logged, or a writer bug in the other repo stays invisible."""
    _write(marker, reset_at=NOW * 1000, observed_at=NOW, observed_by="otto-coordinator")
    with caplog.at_level("WARNING"):
        assert usage_wall.read(now=NOW) is None
    assert usage_wall.is_blocked(now=NOW) is False
    assert any("implausible" in m.lower() for m in caplog.messages), caplog.messages


def test_a_week_out_still_blocks(marker):
    """FALSIFIER for the test above: the boundary must not reject a real weekly wall."""
    _write(marker, reset_at=NOW + (6 * 24 * 3600), observed_at=NOW, observed_by="otto")
    assert usage_wall.is_blocked(now=NOW) is True


# --------------------------------------------------------------------------- observe()

def test_observe_records_the_clis_own_epoch(marker):
    got = usage_wall.observe("Claude AI usage limit reached|1800003600", now=NOW)
    assert got == 1_800_003_600.0
    data = json.loads(marker.read_text())
    assert data["reset_at"] == 1_800_003_600.0
    assert data["observed_by"] == "prospector"


def test_observe_ignores_a_402_credit_exhaustion(marker):
    """A 402 is exhaustion but NOT a subscription wall: it has no reset time and applies to a
    metered API key, not the shared plan. Recording it would bench Otto for a cooldown over a
    fact that does not affect Otto at all."""
    assert usage_wall.observe("claude cli exit 1: 402 credit balance too low", now=NOW) is None
    assert not marker.exists()


def test_observe_falls_back_to_a_cooldown_when_no_reset_is_stated(marker):
    got = usage_wall.observe("Claude AI usage limit reached", now=NOW)
    assert got is not None
    # A bounded cooldown, never an invented multi-hour outage.
    assert 0 < got - NOW <= usage_wall.DEFAULT_COOLDOWN_S


def test_observe_never_shortens_a_live_wall(marker):
    """Two daemons meeting the same wall in the same second must not race into an early resume."""
    _write(marker, reset_at=NOW + 3600, observed_at=NOW, observed_by="otto-coordinator")
    got = usage_wall.observe("Claude AI usage limit reached", now=NOW)   # ~900s cooldown
    assert got == NOW + 3600
    assert json.loads(marker.read_text())["observed_by"] == "otto-coordinator"


def test_observe_extends_a_shorter_wall(marker):
    """FALSIFIER for the test above: a LATER reset must win, or a real extension is lost."""
    _write(marker, reset_at=NOW + 60, observed_at=NOW, observed_by="otto-coordinator")
    got = usage_wall.observe("Claude AI usage limit reached|1800007200", now=NOW)
    assert got == 1_800_007_200.0
    assert json.loads(marker.read_text())["observed_by"] == "prospector"


def test_marker_schema_matches_the_hermes_side(marker):
    """THE CROSS-REPO CONTRACT. The marker is a file, not a shared library, so nothing but a
    test stops the two writers drifting apart. Prove Otto's own reader accepts what we write."""
    hermes = Path(os.path.expanduser("~/.hermes/scripts/claude_usage_limit.py"))
    if not hermes.exists():
        pytest.skip("Hermes side not present in this checkout")
    usage_wall.observe("Claude AI usage limit reached|1800003600", now=NOW)

    spec = importlib.util.spec_from_file_location("_hermes_usage_limit", hermes)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.MARKER = str(marker)            # its own contract: the path is the only coupling

    theirs = mod.read(now=NOW)
    assert theirs is not None, "Otto cannot read a marker Prospector wrote"
    assert theirs["reset_at"] == 1_800_003_600.0
    assert mod.blocked_until(now=NOW) == 1_800_003_600.0
    ours = json.loads(marker.read_text())
    assert set(ours) == {"reset_at", "observed_at", "observed_by", "source"}


# ------------------------------------------------------- rail 1: the CLI never spawns

def test_run_claude_cli_does_not_spawn_into_a_known_wall(marker, monkeypatch):
    from prospector import claude_cli

    def _boom(*a, **k):
        raise AssertionError("spawned the CLI into a wall we could already see")

    monkeypatch.setattr(claude_cli, "_attempt_claude_cli", _boom)
    _write(marker, reset_at=usage_wall.time.time() + 600, observed_at=0,
           observed_by="otto-coordinator")

    with pytest.raises(ProviderExhaustedError) as ei:
        claude_cli.run_claude_cli("hello")
    # The message must carry the CLI's own words so `looks_exhausted`/`classify_exhaustion`
    # reach the same verdict they would on a real wall — otherwise no dead mark is written.
    from prospector.errors import PERMANENT, classify_exhaustion, looks_exhausted
    assert looks_exhausted(str(ei.value))
    assert classify_exhaustion(str(ei.value)) == PERMANENT


def test_run_claude_cli_does_spawn_when_there_is_no_wall(marker, monkeypatch):
    """FALSIFIER: without this, the test above would also pass if the preflight blocked
    unconditionally — i.e. if the daemon never called the CLI at all."""
    from prospector import claude_cli

    calls = []
    monkeypatch.setattr(claude_cli, "_attempt_claude_cli",
                        lambda *a, **k: calls.append(1) or "ok")
    assert not marker.exists()
    assert claude_cli.run_claude_cli("hello") == "ok"
    assert calls == [1]


# --------------------------------------------- rail 2: the tick skips, and retries soon

def test_tick_unproductive_counts_a_usage_wall_skip():
    from prospector.scheduler.run_scheduled import _tick_unproductive
    assert _tick_unproductive({"usage_wall": True}) is True
    # FALSIFIER: a productive tick must still be productive.
    assert _tick_unproductive(
        {"allowed": True, "dry_run": False, "result": {"dossiers": 3}}) is False


# ------------------------------------------- rail 3: the unlist queue always drains

def _cfg(tmp_path) -> types.SimpleNamespace:
    return types.SimpleNamespace(store_dir=str(tmp_path))


def test_unlist_pass_is_free_when_the_queue_is_empty(tmp_path, monkeypatch):
    import subprocess

    from prospector.scheduler.run_scheduled import _unlist_pass
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: pytest.fail("spawned a fly round trip for an empty queue"))
    assert _unlist_pass(_cfg(tmp_path)) is None


def test_decay_pass_drains_the_unlist_queue_even_when_the_sweep_is_off(tmp_path, monkeypatch):
    """THE BUG THIS FILE EXISTS FOR. `pending_unlist.jsonl` had a writer and no caller, so a
    re-vetted KILL kept selling: 4 packs on 2026-08-06, 2 more on 2026-08-07. Turning the decay
    sweep off must not strand a queue an earlier tick already wrote."""
    import subprocess

    from prospector.scheduler.run_scheduled import _decay_pass
    q = tmp_path / "scheduler" / "pending_unlist.jsonl"
    q.parent.mkdir(parents=True, exist_ok=True)
    q.write_text(json.dumps({"candidate_id": "deadbeefdeadbeef", "title": "x"}) + "\n",
                 encoding="utf-8")

    seen = {}

    def _fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return types.SimpleNamespace(returncode=0, stdout="unlisted 1 pack(s)", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    out = _decay_pass(_cfg(tmp_path), 0)          # sweep OFF
    assert out is not None and out["unlisted"]["rc"] == 0
    assert str(seen["cmd"][1]).endswith("tools/unlist_killed.py")


def test_unlist_failure_never_raises_into_the_tick(tmp_path, monkeypatch):
    """A Fly outage must cost the shelf, not the daemon."""
    import subprocess

    from prospector.scheduler.run_scheduled import _decay_pass
    q = tmp_path / "scheduler" / "pending_unlist.jsonl"
    q.parent.mkdir(parents=True, exist_ok=True)
    q.write_text(json.dumps({"candidate_id": "deadbeefdeadbeef"}) + "\n", encoding="utf-8")

    def _raise(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 180)

    monkeypatch.setattr(subprocess, "run", _raise)
    out = _decay_pass(_cfg(tmp_path), 0)
    assert "error" in out["unlisted"] and "Timeout" in out["unlisted"]["error"]
