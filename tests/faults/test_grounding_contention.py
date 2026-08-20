"""Grounding-layer contention resilience (Part 9).

The original cascade had two compounding causes: (1) a provider was permanently
retired on its first transient failure (covered by test_failover breaker tests),
and (2) the concurrency-slot wait sat OUTSIDE the timeout, so a saturated provider
could block a vet indefinitely. These tests pin the second fix: a bounded slot
acquire that fails FAST to failover, and config-driven concurrency."""
from __future__ import annotations

import pytest

import prospector.claude_cli as C
import prospector.gemini_cli as G
from prospector.cli_governor import make_governor


@pytest.fixture(autouse=True)
def _reset_concurrency(monkeypatch, tmp_path):
    """Module-global semaphores are mutated by these tests — restore defaults after."""
    monkeypatch.delenv("PROSPECTOR_GEMINI_CONCURRENCY", raising=False)
    monkeypatch.delenv("PROSPECTOR_CLAUDE_CONCURRENCY", raising=False)
    # Claude's governor is a CrossProcessSemaphore backed by lock FILES under
    # ~/.prospector/cli_slots (cli_governor._slot_root), deliberately shared by every
    # prospector process on the machine. So "occupy the only slot" below was competing with
    # the real daemon for the real budget: with `configure_concurrency(1)` only slot_0 is
    # ever tried, and on 2026-08-01 the scheduler (pid 89502) held all four claude slot
    # files, so the acquire returned False and this file failed on any machine where
    # prospector was actually running — blocking every commit through the POPDD gate for a
    # reason that had nothing to do with the change being committed.
    # PROSPECTOR_CLI_SLOTS is the documented escape hatch for exactly this
    # (cli_governor.py:92); tests/unit/test_cli_governor_scope.py proves it takes effect.
    monkeypatch.setenv("PROSPECTOR_CLI_SLOTS", str(tmp_path / "cli_slots"))
    # Rebuild rather than trust configure_concurrency(): it is a no-op when the requested
    # size already equals _MAX_CLI (claude_cli.py:64), which would silently leave the
    # machine-wide governor in place and reintroduce the coupling.
    monkeypatch.setattr(C, "_CLI_SEM", make_governor(C._MAX_CLI, "claude"))
    yield
    G.configure_concurrency(2)
    C.configure_concurrency(2)


def test_gemini_bounded_acquire_fails_fast_when_saturated():
    """When every slot is taken, a grounding call gives up after queue_timeout with a
    'saturated' RuntimeError (a transient failure -> failover) instead of blocking —
    and never reaches subprocess.run, so no real CLI is spawned."""
    G.configure_concurrency(1)
    assert G._CLI_SEM.acquire(timeout=1)         # occupy the only slot
    try:
        with pytest.raises(RuntimeError, match="saturated"):
            G._attempt_gemini_cli(["true"], timeout=5, web=False, queue_timeout=0.05)
    finally:
        G._CLI_SEM.release()


def test_claude_bounded_acquire_fails_fast_when_saturated():
    C.configure_concurrency(1)
    assert C._CLI_SEM.acquire(timeout=1)
    try:
        with pytest.raises(RuntimeError, match="saturated"):
            C._attempt_claude_cli(["true"], timeout=5, web=False, queue_timeout=0.05)
    finally:
        C._CLI_SEM.release()


def test_configure_concurrency_resizes_from_config():
    G.configure_concurrency(4)
    assert G._MAX_CLI == 4
    # Claude does NOT resize. Founder directive 2026-08-21, repeated: "i dont want consurreny
    # onclaude code", "its too expencice". `configure_concurrency` clamps down to
    # claude_cli._CLAUDE_MAX_EVER, so asking for 3 gets 1. The clamp itself is proved in
    # tests/unit/test_claude_cli_is_never_concurrent.py; this asserts it holds on the path
    # config actually takes.
    C.configure_concurrency(3)
    assert C._MAX_CLI == C._CLAUDE_MAX_EVER == 1


def test_env_var_pins_concurrency_over_config(monkeypatch):
    """The ops escape hatch wins: if the env var is set, config can't override it."""
    monkeypatch.setenv("PROSPECTOR_GEMINI_CONCURRENCY", "1")
    G.configure_concurrency(8)        # config asks for 8...
    assert G._MAX_CLI != 8            # ...but the env-pinned value stands (no-op)
