"""A scheduler cfg that does not say where the store is must fail, not guess.

MEASURED 2026-08-06 on the live store.

`store/scheduler/ticks.jsonl` holds 1258 rows. 110 of them (8.8%) are stamped 1970-01-01 through
1970-01-03, sitting at line indexes 687..796 between a 2026-07-30T18:43 neighbour and a
2026-07-28T00:50 one, every single one identical in shape::

    {"ts": "1970-01-01T00:02:30.273681+00:00", "allowed": true,
     "reason": "ok: $0.0000 of $20.00 spent today", "dry_run": false,
     "today_spend_usd": 0.0, "daily_cap_usd": 20.0, "batch_size": 5,
     "result": {"dossiers": 0, "passes": 0, "defers": 0, "provisional": 0}, "error": null}

An epoch clock and $0.0000 of spend on a machine that spends: no real tick has ever looked like
that. They were written by a test whose cfg had no `store_dir`, because all three scheduler path
helpers resolved that case to the RELATIVE literal ``"store"``::

    prospector/scheduler/guard.py:201        Path(getattr(cfg, "store_dir", "store"))
    prospector/scheduler/run_scheduled.py:75 Path(getattr(cfg, "store_dir", "store"))
    prospector/scheduler/alerts.py:51        Path(getattr(cfg, "store_dir", "store")) / "scheduler"

Under pytest the cwd is the repo root, so `./store` IS the production store. Two more rows landed
the same way on 2026-08-06 while writing `test_tick_hard_deadline.py`.

This is the `_AUDIT_DIR`-binds-at-import bug in another costume, and it gets the same answer: the
unconfigured case must be impossible rather than quiet. These tests pin that the raise happens at
every seam a test double can enter through — and that the message says what to do about it, since
the failure will land on someone who has never read this file.
"""
from __future__ import annotations

import types

import pytest

from prospector.scheduler import alerts, guard, paths
from prospector.scheduler import run_scheduled as rs


class _NoStoreDir:
    """A hand-rolled double of the shape that caused the pollution: no `store_dir` at all."""


@pytest.mark.parametrize("call,seam", [
    (lambda c: paths.store_dir(c), "paths.store_dir"),
    (lambda c: paths.scheduler_dir(c), "paths.scheduler_dir"),
    (lambda c: rs._store_dir(c), "run_scheduled._store_dir"),
    (lambda c: rs._ticks_path(c), "run_scheduled._ticks_path (writes ticks.jsonl)"),
    (lambda c: rs._heartbeat_path(c), "run_scheduled._heartbeat_path"),
    (lambda c: guard._store_dir(c), "guard._store_dir (reads the spend ledger)"),
    (lambda c: alerts._scheduler_dir(c), "alerts._scheduler_dir (writes ALERT.txt)"),
])
@pytest.mark.parametrize("cfg", [_NoStoreDir(), types.SimpleNamespace()],
                         ids=["plain-object", "SimpleNamespace"])
def test_no_seam_silently_falls_back_to_the_cwd(call, seam, cfg, tmp_path, monkeypatch):
    """Run from a scratch cwd so a fallback would be visible rather than merely wrong."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="store_dir"):
        call(cfg)
    assert not (tmp_path / "store").exists(), (
        f"{seam} created a store relative to the cwd; under pytest that cwd is the repo root"
    )


def test_the_error_tells_the_reader_how_to_fix_it():
    with pytest.raises(ValueError) as exc:
        paths.store_dir(types.SimpleNamespace())
    msg = str(exc.value)
    assert "SimpleNamespace" in msg, "name the offending type — the caller is usually a test double"
    assert "store_dir=tmp_path" in msg, "the remedy has to be in the message, not in a docstring"


def test_a_configured_store_dir_is_honoured_unchanged(tmp_path):
    cfg = types.SimpleNamespace(store_dir=str(tmp_path))
    assert paths.store_dir(cfg) == tmp_path
    assert rs._ticks_path(cfg) == tmp_path / "scheduler" / "ticks.jsonl"
    assert alerts._scheduler_dir(cfg) == tmp_path / "scheduler"
    assert (tmp_path / "scheduler").is_dir(), "the scheduler dir is still created on demand"


def test_a_falsy_but_present_store_dir_is_not_treated_as_missing(tmp_path, monkeypatch):
    """`getattr(cfg, 'store_dir', None) or ...` would send an empty string back to the cwd.

    The check is `is None` on purpose. An empty `store_dir` is a configuration error that should
    surface as a path error at the point of use, not get quietly rewritten into the repo root.
    """
    monkeypatch.chdir(tmp_path)
    assert str(paths.store_dir(types.SimpleNamespace(store_dir=""))) == "."
