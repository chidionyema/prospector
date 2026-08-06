"""A scheduler cfg that does not say where the store is must fail, not guess.

All three scheduler path helpers resolved a cfg with no `store_dir` to the RELATIVE literal
``"store"``::

    prospector/scheduler/guard.py:201        Path(getattr(cfg, "store_dir", "store"))
    prospector/scheduler/run_scheduled.py:75 Path(getattr(cfg, "store_dir", "store"))
    prospector/scheduler/alerts.py:51        Path(getattr(cfg, "store_dir", "store")) / "scheduler"

Under pytest the cwd is the repo root, so `./store` IS the production store — a test double that
forgets one attribute silently exercises production instead of `tmp_path`. That is not a
hypothetical class of bug here: `_AUDIT_DIR` is bound at import (`prospector/audit.py:133-136`),
which is exactly how pytest reached the live audit log.

CORRECTION (2026-08-06): this docstring previously offered 110 epoch-stamped rows in
`store/scheduler/ticks.jsonl` as the proof, asserting "no real tick has ever looked like that".
Re-measured against all 1312 rows, that was false — the shape is 1069 of them, `dossiers: 0` is
58%, `$0.0000` is 53%, and their spacing (median ~38 min, none under 10s) plus `batch_size: 5`
(the pre-2026-07-31 config) says daemon under a bad clock, not test double. See
`prospector/scheduler/paths.py` for the full table. The fence stands on the mechanism above; it
never needed those rows, and citing them as if it did is the failure this note exists to record.

These tests pin that the raise happens at every seam a test double can enter through — and that
the message says what to do about it, since the failure will land on someone who has never read
this file.
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
