"""CLI concurrency + query-gen timeout caps wired from retrieval config."""
from __future__ import annotations

from prospector.config import load_config
from prospector import cursor_cli
from prospector.operator import _build_operator


def test_config_loads_concurrency_and_timeout_knobs():
    cfg = load_config()
    r = cfg.retrieval
    # Raised from 2/2/2 on 2026-07-31 once prospector/cli_governor.py made the cap
    # machine-wide (flock) instead of per-process. 8 is the measured knee of the concurrent
    # `agent` subprocess probe (N=8: 8/8 ok, p50 9.2s; N=14: p50 13.1s for +13% throughput).
    assert r.vet_workers == 5
    assert r.claude_concurrency == 4
    assert r.cursor_concurrency == 8
    # The invariant that outlives the tuned numbers: a vet runs its checks SEQUENTIALLY
    # (verify.py:667, required by kill-fast), so it holds at most one CLI slot at a time.
    # vet_workers > cursor_concurrency would therefore guarantee slot starvation and
    # re-create the "grounding queue saturated" failure this change exists to remove.
    assert r.vet_workers <= r.cursor_concurrency, "workers must not outnumber CLI slots"
    assert r.query_gen_timeout == 90
    assert r.query_gen_timeout_max == 90
    assert r.query_gen_retries == 0
    # Raised from 120/180 on 2026-07-31. The old ceiling sat INSIDE the observed success
    # distribution (317 logged run_cursor_cli successes: p50 41.7s, max 279.3s), so healthy
    # long calls were killed mid-flight — every logged cursor error had p50 exactly 120.0s,
    # the guillotine rather than a hang. Each kill cost 2 x 120s and returned nothing, which
    # is how packs ended up held back on "artifact 'build_spec' is empty". See config.yaml.
    assert r.cli_timeout == 180
    assert r.cli_timeout_max == 300
    # The invariant that actually matters, independent of the tuned numbers: the ceiling must
    # sit ABOVE the slowest call we have ever seen succeed, or the timeout is a correctness
    # bug (it manufactures empty artifacts) rather than a resource guard.
    assert r.cli_timeout_max >= 280, "ceiling must exceed the observed 279.3s success"
    assert r.cli_timeout <= r.cli_timeout_max


def test_cursor_fast_op_uses_query_gen_timeout_cap():
    cfg = load_config()
    op = _build_operator("cursor_cli", cfg, fast=True)
    assert isinstance(op, cursor_cli.CursorCliOperator)
    assert op.timeout == cfg.retrieval.query_gen_timeout
    assert op.timeout_max == cfg.retrieval.query_gen_timeout_max
    assert op.retries == cfg.retrieval.query_gen_retries


def test_cursor_moat_op_uses_cli_timeout():
    cfg = load_config()
    op = _build_operator("cursor_cli", cfg, fast=False)
    assert isinstance(op, cursor_cli.CursorCliOperator)
    assert op.timeout == cfg.retrieval.cli_timeout
    assert op.timeout_max == cfg.retrieval.cli_timeout_max
    assert op.retries == cfg.retrieval.cli_retries


def test_configure_concurrency_from_config(monkeypatch):
    monkeypatch.delenv("PROSPECTOR_CURSOR_CONCURRENCY", raising=False)
    cursor_cli.configure_concurrency(3)
    assert cursor_cli._MAX_CLI == 3
    # Env wins — configure must no-op when set.
    monkeypatch.setenv("PROSPECTOR_CURSOR_CONCURRENCY", "1")
    cursor_cli.configure_concurrency(9)
    assert cursor_cli._MAX_CLI == 3  # unchanged while env pins
