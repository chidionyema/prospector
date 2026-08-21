"""CLI concurrency + query-gen timeout caps wired from retrieval config.

Rewritten 2026-08-06 when the cursor_cli adapter was deleted (founder directive). The three
cursor-specific tests went with it; what survives is the pair of INVARIANTS they existed to
protect, retargeted at claude_cli — which is now the only CLI brain, and therefore the only
thing `vet_workers` can starve.
"""
from __future__ import annotations

from prospector import claude_cli
from prospector.config import load_config


def test_config_loads_concurrency_and_timeout_knobs():
    cfg = load_config()
    r = cfg.retrieval
    # ONE since 2026-08-20 (founder: "1 cludclaude cli", "not 4", "its epensive"). Four
    # concurrent claude Node runtimes measured 91.7% host steal inside prospector-engine and
    # starved the ops console. The number is welded by claude_cli.MAX_CLAUDE_CLI;
    # tests/unit/test_one_claude_cli_process.py is where that rule lives.
    assert r.claude_concurrency == 1
    assert r.vet_workers == 8
    assert not hasattr(r, "cursor_concurrency"), "cursor_cli knob was removed 2026-08-06"
    # THE INVARIANT, retargeted 2026-08-15. It outlives the tuned numbers and it was never
    # really about claude_cli: a vet runs its checks SEQUENTIALLY (verify.py:667, required by
    # kill-fast), so it holds at most one slot on ONE brain at a time. More workers than that
    # brain has slots guarantees starvation and re-creates the "grounding queue saturated"
    # failure.
    #
    # What changed is WHICH brain. `claude_concurrency` was the whole ceiling only while
    # claude_cli was the only brain in the chain; since minimax was promoted to head both
    # `operator:` and `moat_primary:` (config.yaml:58,81), the head's ceiling is the one that
    # binds and claude_concurrency bounds the FAILOVER. Pinning the old brand here is pinning
    # the roster, not the invariant — the same defect tests/test_drain_moat_preflight.py's
    # fixture docstring records — so this reads the head of the configured chain.
    head = cfg.operator[0] if isinstance(cfg.operator, list) else cfg.operator
    ceiling = getattr(r, f"{head}_concurrency", None)
    assert ceiling is not None, f"the chain head {head!r} declares no concurrency ceiling"
    assert r.vet_workers <= ceiling, (
        f"workers ({r.vet_workers}) must not outnumber {head} slots ({ceiling})")
    assert r.query_gen_timeout == 90
    assert r.query_gen_timeout_max == 90
    assert r.query_gen_retries == 0
    # Raised from 120/180 on 2026-07-31. The old ceiling sat INSIDE the observed success
    # distribution (317 logged CLI successes: p50 41.7s, max 279.3s), so healthy long calls
    # were killed mid-flight — every logged CLI error had p50 exactly 120.0s, the guillotine
    # rather than a hang. Each kill cost 2 x 120s and returned nothing, which is how packs
    # ended up held back on "artifact 'build_spec' is empty". See config.yaml.
    assert r.cli_timeout == 180
    assert r.cli_timeout_max == 300
    # The invariant that actually matters, independent of the tuned numbers: the ceiling must
    # sit ABOVE the slowest call we have ever seen succeed, or the timeout is a correctness
    # bug (it manufactures empty artifacts) rather than a resource guard.
    assert r.cli_timeout_max >= 280, "ceiling must exceed the observed 279.3s success"
    assert r.cli_timeout <= r.cli_timeout_max


def test_configure_concurrency_from_config(monkeypatch):
    """Config reaches the governor, and the clamp bounds it.

    Rewritten 2026-08-20. This used to prove config could resize to 3 and that the env var
    beat config outright. Both halves are now bounded by claude_cli.MAX_CLAUDE_CLI = 1:
    config and env may both LOWER the width, neither may raise it. What survives is the
    invariant the test existed for -- these knobs reach the real semaphore rather than
    sitting in a dataclass nothing reads.
    """
    original = claude_cli._MAX_CLI
    try:
        monkeypatch.delenv("PROSPECTOR_CLAUDE_CONCURRENCY", raising=False)
        claude_cli.configure_concurrency(3)
        assert claude_cli._MAX_CLI == 1, "config asked for 3 and the clamp let it through"
        monkeypatch.setenv("PROSPECTOR_CLAUDE_CONCURRENCY", "9")
        claude_cli.configure_concurrency(9)
        assert claude_cli._MAX_CLI == 1, "the env var reopened the door to four runtimes"
    finally:
        monkeypatch.delenv("PROSPECTOR_CLAUDE_CONCURRENCY", raising=False)
        claude_cli.configure_concurrency(original)
