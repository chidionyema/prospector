"""The token ledger must close: every token in `total` sits in a named, priced column.

WHY THIS FILE EXISTS (2026-08-13, war-plan W0.3). The batch of 2026-08-13T06:23:14 reported
`input 420,082 + output 308,297 = 728,379` against a `total` of `1,990,168`, and
`claude_cli input: 70`. That was read as a broken cost instrument, and it condemned every
per-phase and per-stage figure derived from it.

The instrument was not broken. `total` is a FIVE-term sum (`claude_cli.py:78`) of which
`telemetry._USAGE_KEYS` carried only four columns, so the fifth — `cache_creation` — had
nowhere to land and showed up as an unexplained 1.26M residual. `input: 70` was likewise
correct: under prompt caching `input_tokens` is only the UNCACHED remainder.

These tests pin the two things that made it unreadable:
  1. the identity `total == input + output + cached + cache_write`, and
  2. that `reconcile()` reports a residual instead of asserting, so a provider whose
     `total_tokens` means something else stays visible rather than crashing a batch.
"""
from __future__ import annotations

import pytest

from prospector import telemetry


@pytest.fixture(autouse=True)
def _clean_ledger():
    telemetry.reset_usage()
    yield
    telemetry.reset_usage()


def test_the_batch_that_looked_corrupt_reconciles_exactly():
    """The real numbers from `store/scheduler/batch_diagnostics.jsonl`, 2026-08-13T06:23:14.

    Recorded as one claude_cli call so the arithmetic is the ledger's, not the test's.
    """
    telemetry.record_usage(
        input_tokens=70, output_tokens=47_269, cached_tokens=647_108,
        cache_write_tokens=614_681,
        total_tokens=70 + 47_269 + 647_108 + 614_681,
        provider="claude_cli")
    summary = telemetry.get_usage_summary()

    assert summary["total"]["total"] == 1_309_128
    assert summary["reconcile"]["residual"] == 0, (
        "the ledger did not close; some tokens in `total` have no priced column: "
        f"{summary['reconcile']}")
    assert summary["by_provider"]["claude_cli"]["reconcile"]["residual"] == 0


def test_cache_write_is_a_column_not_just_a_term_of_total():
    """The whole defect: the fifth term existed in the SUM but had nowhere to be stored.

    Without its own key, `cache_write` tokens are invisible and the residual is non-zero —
    which is exactly the state that read as corruption.
    """
    assert "cache_write" in telemetry._USAGE_KEYS

    telemetry.record_usage(input_tokens=10, output_tokens=20, cached_tokens=30,
                           cache_write_tokens=40, total_tokens=100, provider="claude_cli")
    agg = telemetry.get_usage_summary()["total"]
    assert agg["cache_write"] == 40
    assert telemetry.reconcile(agg)["residual"] == 0


def test_an_unattributed_total_shows_up_as_a_residual_and_does_not_raise():
    """A provider whose `total_tokens` we cannot reproduce must stay VISIBLE, not fatal.

    MiniMax, DeepSeek, Ollama, StandardCompute and OpenRouter each pass through their own
    `usage.total_tokens` (`operator.py:459`, `:554`, `:1061`, `:677`, `:956`). Raising here
    would turn one vendor's accounting quirk into a crashed batch; the residual attributes
    it instead.
    """
    telemetry.record_usage(input_tokens=100, output_tokens=100, total_tokens=500,
                           provider="someprovider")
    summary = telemetry.get_usage_summary()
    assert summary["reconcile"]["residual"] == 300
    assert summary["by_provider"]["someprovider"]["reconcile"]["residual"] == 300


def test_residual_is_attributed_to_the_provider_that_caused_it():
    """The aggregate alone is not actionable: it spreads one adapter's gap over the batch."""
    telemetry.record_usage(input_tokens=1, output_tokens=1, cached_tokens=0,
                           cache_write_tokens=0, total_tokens=2, provider="claude_cli")
    telemetry.record_usage(input_tokens=1, output_tokens=1, total_tokens=99,
                           provider="minimax")
    by_prov = telemetry.get_usage_summary()["by_provider"]
    assert by_prov["claude_cli"]["reconcile"]["residual"] == 0
    assert by_prov["minimax"]["reconcile"]["residual"] == 97


def test_existing_callers_are_unaffected_by_the_new_kwarg():
    """`cache_write_tokens` defaults to 0, so the ~19 call sites that never pass it still work."""
    telemetry.record_usage(input_tokens=5, output_tokens=5, total_tokens=10,
                           provider="mock")
    assert telemetry.get_usage_summary()["total"]["cache_write"] == 0
