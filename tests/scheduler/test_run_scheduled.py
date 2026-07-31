"""The always-on daemon must generate when permitted, skip when guarded, and never die on a
single batch failure."""
from __future__ import annotations

import json
import types
from pathlib import Path

from prospector.scheduler import run_scheduled as rs


def _cfg(tmp_path, cap=20.0, batch=3):
    return types.SimpleNamespace(
        store_dir=str(tmp_path),
        spend=types.SimpleNamespace(daily_cap_usd=cap, warn_at_usd=cap * 0.75),
        schedule={"batch_size": batch},
    )


def _ticks(tmp_path):
    p = Path(tmp_path) / "scheduler" / "ticks.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def test_tick_runs_when_permitted(tmp_path):
    calls = []
    tick = rs.run_tick(_cfg(tmp_path), generate_fn=lambda c, n: calls.append(n) or {"dossiers": n})
    assert tick["allowed"]
    assert calls == [3]  # config batch_size
    assert tick["result"] == {"dossiers": 3}
    assert len(_ticks(tmp_path)) == 1


def test_candidates_override_batch_size(tmp_path):
    calls = []
    rs.run_tick(_cfg(tmp_path), candidates=7, generate_fn=lambda c, n: calls.append(n))
    assert calls == [7]


def test_tick_skips_when_paused(tmp_path):
    sd = Path(tmp_path) / "scheduler"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "PAUSE").write_text("")
    calls = []
    tick = rs.run_tick(_cfg(tmp_path), generate_fn=lambda c, n: calls.append(n))
    assert not tick["allowed"]
    assert calls == []
    assert "paused" in tick["reason"]


def test_dry_run_never_generates(tmp_path):
    calls = []
    tick = rs.run_tick(_cfg(tmp_path), dry_run=True, generate_fn=lambda c, n: calls.append(n))
    assert tick["allowed"]
    assert calls == []


def test_tick_survives_generation_error(tmp_path):
    def boom(c, n):
        raise RuntimeError("moat exhausted")

    tick = rs.run_tick(_cfg(tmp_path), generate_fn=boom)
    assert tick["error"] and "moat exhausted" in tick["error"]
    # Still logged, so the audit trail records the failure.
    assert len(_ticks(tmp_path)) == 1


def test_daemon_runs_max_cycles(tmp_path):
    calls = []
    n = rs.run_daemon(
        _cfg(tmp_path), interval=0,
        generate_fn=lambda c, k: calls.append(k),
        max_cycles=2, sleep_fn=lambda s: None,
    )
    assert n == 2
    assert calls == [3, 3]


def test_daemon_idles_when_paused(tmp_path):
    sd = Path(tmp_path) / "scheduler"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "PAUSE").write_text("")
    calls = []
    n = rs.run_daemon(
        _cfg(tmp_path), interval=0,
        generate_fn=lambda c, k: calls.append(k),
        max_cycles=3, sleep_fn=lambda s: None,
    )
    assert n == 3
    assert calls == []  # paused every cycle, never generated
