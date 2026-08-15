"""A cockpit zero must not be able to mean "the read threw".

`load_overview_kpis` fans out over sqlite, the spend ledger, golden runs and the config
behind one `except Exception: return {}`.  Every consumer then reads a missing key as 0
(`pages/_reports.py`, `pages/_overview.py:225`), so a store that could not be read renders
as `PASS 0 · KILL 0 · $0.00 · 0 dossiers` — the same screen a quiet, healthy estate draws.
That is the defect that once let a CI mock's canned 1.0 be reported as the moat's live gate
score: a confident number with nothing behind it.

The fix does not stop the degradation (a Streamlit panel that raises takes the page down).
It makes the degradation *tellable*: `overview_kpis_error()` is empty when the numbers are
real and carries the exception when they are not.  These tests pin the DISTINCTION — that
the two cases produce identical numbers and differ only in the error channel.
"""
from __future__ import annotations

import sqlite3

import pytest

from prospector.control_center import readers

_ZEROED_STATS = {
    "total": 0, "n_pass": 0, "n_kill": 0, "n_defer": 0, "n_provisional": 0,
    "n_pass_non_prov": 0, "n_pass_provisional": 0, "n_listed": 0,
    "pass": 0, "kill": 0, "defer": 0,
}


def _clear_caches() -> None:
    for name in (
        "load_overview_kpis", "overview_kpis_error", "load_config_typed",
        "config_load_error", "load_provider_health", "provider_health_error",
        "latest_golden", "load_golden_runs", "load_pending_signals",
    ):
        fn = getattr(readers, name, None)
        clear = getattr(fn, "clear", None)
        if clear is not None:
            clear()


@pytest.fixture()
def empty_store(monkeypatch, tmp_path):
    monkeypatch.setenv("PROSPECTOR_STORE_ROOT", str(tmp_path / "store"))
    _clear_caches()
    yield
    _clear_caches()


def test_an_empty_store_and_a_broken_read_differ_only_in_the_error_channel(
    monkeypatch, empty_store
):
    # 1. A genuinely empty store: real zeros, no error.
    monkeypatch.setattr(readers, "catalogue_stats", lambda: dict(_ZEROED_STATS))
    healthy = readers.load_overview_kpis()
    assert readers.overview_kpis_error() == ""
    assert healthy, "an empty store must still produce a KPI dict"

    # 2. The same call with the index unreadable.
    _clear_caches()

    def _malformed():
        raise sqlite3.DatabaseError("database disk image is malformed")

    monkeypatch.setattr(readers, "catalogue_stats", _malformed)
    broken = readers.load_overview_kpis()

    # The numbers are IDENTICAL — this is why the old silent `{}` was a lie with a
    # confident face, and why asserting on them alone would pin nothing.
    for key in ("pass_count", "kill_count", "defer_count", "n_listed", "total"):
        assert healthy.get(key, 0) == broken.get(key, 0) == 0

    # Only the error channel separates them.
    err = readers.overview_kpis_error()
    assert "database disk image is malformed" in err
    assert "DatabaseError" in err


def test_provider_health_absent_is_healthy_but_corrupt_is_unknown(monkeypatch, tmp_path):
    """`{}` from this reader is drawn as "every operator healthy" (pages/_diagnostics.py).

    Absence really does mean no breaker ever tripped.  A corrupt file means we do not know,
    and painting the moat green off an unreadable file is the loudest possible lie.
    """
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("PROSPECTOR_STORE_ROOT", str(store))
    _clear_caches()

    # Absent: a value, not a failure.
    assert readers.load_provider_health() == {}
    assert readers.provider_health_error() == ""

    # Present and corrupt: same `{}`, but now it says so.
    _clear_caches()
    (store / "provider_health.json").write_text("{not json", encoding="utf-8")
    assert readers.load_provider_health() == {}
    err = readers.provider_health_error()
    assert "JSONDecodeError" in err

    # Present and healthy: real content, still no error.
    _clear_caches()
    (store / "provider_health.json").write_text(
        '{"claude_cli": {"dead_until": 0}}', encoding="utf-8"
    )
    assert readers.load_provider_health() == {"claude_cli": {"dead_until": 0}}
    assert readers.provider_health_error() == ""
    _clear_caches()
