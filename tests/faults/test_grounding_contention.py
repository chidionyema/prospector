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


@pytest.fixture(autouse=True)
def _reset_concurrency(monkeypatch):
    """Module-global semaphores are mutated by these tests — restore defaults after."""
    monkeypatch.delenv("PROSPECTOR_GEMINI_CONCURRENCY", raising=False)
    monkeypatch.delenv("PROSPECTOR_CLAUDE_CONCURRENCY", raising=False)
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
    C.configure_concurrency(3)
    assert C._MAX_CLI == 3


def test_env_var_pins_concurrency_over_config(monkeypatch):
    """The ops escape hatch wins: if the env var is set, config can't override it."""
    monkeypatch.setenv("PROSPECTOR_GEMINI_CONCURRENCY", "1")
    G.configure_concurrency(8)        # config asks for 8...
    assert G._MAX_CLI != 8            # ...but the env-pinned value stands (no-op)
