"""Failure-mode tests for the per-tick status digest pusher.

The pusher (`_emit_tick_digest` in `prospector.scheduler.run_scheduled`) is the engine
side of the `🎛 Now` wire-up. It is debounced, exception-safe, and honored under
PYTEST_CURRENT_TEST — same discipline as `_telegram_push` in `tests/scheduler/test_telegram_sink.py`.
"""
from __future__ import annotations

import os
import types
from pathlib import Path


def _cfg(tmp_path: Path) -> types.SimpleNamespace:
    return types.SimpleNamespace(store_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# `status_snapshot` import + shape
# ---------------------------------------------------------------------------

def test_emit_tick_digest_is_defined():
    """The function must exist, on the same module as _emit_tick_alerts (run_scheduled.py)."""
    from prospector.scheduler import run_scheduled as RS
    assert hasattr(RS, "_emit_tick_digest"), "wire-up step: define _emit_tick_digest"


def test_pytest_blocks_real_send(tmp_path, monkeypatch):
    """The same fence as `_telegram_push`: PYTEST_CURRENT_TEST must force dry_run."""
    from prospector.scheduler import run_scheduled as RS

    seen = {}
    def fake_send(text, *, debounce_key=None, debounce_s=300.0, dry_run=False):
        seen.update(text=text, debounce_key=debounce_key, dry_run=dry_run)
        return True

    monkeypatch.setattr(RS, "_load_hermes_sender", lambda: fake_send)
    assert "PYTEST_CURRENT_TEST" in os.environ, "pytest no longer sets this; the fence is broken"
    RS._emit_tick_digest(_cfg(tmp_path), tick={"dossiers": 0, "passes": 0, "kills": 0})
    assert seen.get("dry_run") is True, "pusher must not send for real under pytest"


def test_pusher_uses_2h_debounce(tmp_path, monkeypatch):
    """The debounce key + 7200s must match the spec — keeps the digest from spamming."""
    from prospector.scheduler import run_scheduled as RS

    seen = []
    monkeypatch.setattr(RS, "_load_hermes_sender",
                        lambda: lambda text, **kw: seen.append(kw) or True)

    RS._emit_tick_digest(_cfg(tmp_path), tick={"dossiers": 5, "passes": 1, "kills": 4})
    assert len(seen) == 1
    assert seen[0]["debounce_key"] == "prospector:tick_digest"
    assert seen[0]["debounce_s"] == 7200.0


def test_pusher_swallows_exceptions(tmp_path, monkeypatch):
    """A failed send must not crash the daemon or the tick."""
    from prospector.scheduler import run_scheduled as RS

    def boom(text, **kw):
        raise RuntimeError("telegram unreachable")

    monkeypatch.setattr(RS, "_load_hermes_sender", lambda: boom)
    # No raise
    RS._emit_tick_digest(_cfg(tmp_path), tick={"dossiers": 0, "passes": 0, "kills": 0})


def test_pusher_writes_even_when_no_heartbeat(tmp_path, monkeypatch):
    """A fresh store (no heartbeat, no ticks) still produces a digest — the founder
    should see 'idle' rather than silence."""
    from prospector.scheduler import run_scheduled as RS

    seen = []
    monkeypatch.setattr(RS, "_load_hermes_sender",
                        lambda: lambda text, **kw: seen.append(text) or True)

    RS._emit_tick_digest(_cfg(tmp_path), tick={})
    assert len(seen) == 1
    assert isinstance(seen[0], str)
    assert len(seen[0]) <= 600


def test_pusher_called_after_emit_tick_alerts(tmp_path, monkeypatch):
    """The pusher must be wired at the same six sites as _emit_tick_alerts
    (run_scheduled.py lines 822, 910, 933, 982, 1007, 1020). A grep proves the wiring."""
    import re
    from pathlib import Path
    rs = Path("/Users/chidionyema/Documents/code/prospector/.worktrees/feat-now-telegram-status-digest/prospector/scheduler/run_scheduled.py")
    src = rs.read_text()
    # Both must be called together
    pair = re.findall(r"_emit_tick_alerts\([^)]*\)", src)
    digest = re.findall(r"_emit_tick_digest\([^)]*\)", src)
    assert len(pair) >= 4, f"expected >=4 _emit_tick_alerts, got {len(pair)}"
    assert len(digest) == len(pair), (
        f"wiring mismatch: {len(pair)} _emit_tick_alerts sites but {len(digest)} _emit_tick_digest"
    )
