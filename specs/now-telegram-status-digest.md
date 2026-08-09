# Spec — `feat/now-telegram-status-digest`

> **Engine side** of the "running blind" wire-up. The Hermes-side `🎛 Now` renderer is a
> separate repo and a separate spec.
>
> Worktree: `.worktrees/feat-now-telegram-status-digest`
> Branch: `feat/now-telegram-status-digest` (off `origin/main` @ `e3519ed`)
> Working dir: `cd .worktrees/feat-now-telegram-status-digest`
> Verify: `./.venv/bin/python -m pytest -q` (final); `./.venv/bin/python -m pytest -q tests/unit/test_status_snapshot.py tests/unit/test_tick_digest.py` (gate)
> Note: the worktree has no `.venv` of its own — the leader venv has been symlinked at
> `.worktrees/feat-now-telegram-status-digest/.venv -> ../../.venv`. Tests run with that
> interpreter inside the worktree. The test `test_pusher_called_after_emit_tick_alerts`
> hard-codes the worktree path because the wiring grep must look at the file being edited,
> not at whichever file pytest was imported from.

## 0. Why this exists

The engine emits a fine-grained stream of structured events (per-LLM-call latency/cost, per-tick
results, provider health, active alerts) but **only 5 critical alerts reach Telegram**:
`TELEGRAM_KEYS = frozenset({"liveness", "tick_error", "zero_yield", "barren_streak", "moat_blind"})`
(`prospector/scheduler/alerts.py:267`). The `🎛 Now` view documented in `~/.hermes/OPERATOR_UX_SPEC.md`
§2 cannot currently show engine state because **no `status_snapshot()` exists** and **no periodic
pusher** feeds the existing single Telegram sender (`~/.hermes/scripts/estate_alert.py`).

The "real-time monitoring features that need to be wired" are these existing primitives:
- `prospector/telemetry.py` (token/cost/usage aggregation; `get_usage_summary()`)
- `prospector/progress.py` (per-result console summary)
- `prospector/health.py` (provider circuit breaker, `moat_blind_reason`)
- `prospector/scheduler/alerts.py` (`alerts_for_tick`, `alert_state.json` active alerts)
- `prospector/scheduler/run_scheduled.py` (heartbeat, tick records, `_write_heartbeat`)

This branch composes them into a single `status_snapshot()` and pushes a one-line digest to
Telegram after every tick (debounced 2h). Hermes can then read the same snapshot for its own
renderer.

## 1. Files

### NEW — `prospector/scheduler/status.py`
A pure read-only module. No imports of `claude_cli`, `signals`, `prospector.run` — only `paths`,
`telemetry`, `health`, `json`/`pathlib`. Surface:

```python
def status_snapshot(cfg) -> dict:
    """Read-only engine state, JSON-safe for cross-process transport.

    Returns the union asked for in the planning question:
      - daemon:    {pid, phase, last_tick_age_s, heartbeat_ts}
      - last_tick: {ts, dossiers, passes, kills, defers, provisional, cost_usd, duration_s}
                   — None if no tick on record today
      - spend:     {today_usd, daily_cap_usd, today_subscription_usd, monthly_usd}
      - providers: {moat_blind: bool, dead: list[str], moat_brains: list[str],
                   blind_reason: str|None}
      - alerts:    {active: list[{key, title, severity, ts}], active_count: int}
      - backlog:   {deferred: int|None, provisional: int|None}

    Never raises. On any read failure, the offending field is None and the rest is returned.
    """

def format_status_snapshot(snap: dict) -> str:
    """One Telegram-ready message (≤ 600 chars). No Telegram-specific deps; this module
    must remain renderable from a test invocation that has no heroku socket."""
```

Read sources (only existing files, no new persistence):
- `store/scheduler/heartbeat.json` → daemon pid / phase / ts
- `store/scheduler/ticks.jsonl` → last tick row (last row with `result` set; dry-run budget
  check rows are filtered out — `dry_run=True` plus `result=None`)
- `store/scheduler/audit/<today>.jsonl` → count of `verify_search` events as a proxy for the
  vetting load (last tick only)
- `store/prospector.jsonl` aggregation → today_usd / today_subscription_usd / daily_cap_usd /
  monthly_usd (read the latest `gating-decision` spend records; existing pattern in
  `prospector/scheduler/guard.py:158`)
- `store/provider_health.json` → dead providers + moat_brains list
- `store/scheduler/alert_state.json` → `_active` list
- `store/scheduler/DIAGNOSTICS_LATEST.txt` → moat_blind_reason (if present)
- `store/dossiers/` count for backlog (deferred + provisional by glob; existing pattern
  `_backlog_size` at `run_scheduled.py:193`)

### MODIFY — `prospector/scheduler/run_scheduled.py`
Add after `_emit_tick_alerts(cfg, tick)` (lines 822, 910, 933, 982, 1007, 1020):

```python
def _emit_tick_digest(cfg, tick: dict) -> None:
    """Push a one-line status digest to Telegram after each tick (debounced 2h).

    Mirrors `_telegram_push` discipline: best-effort, never raises, honored under
    PYTEST_CURRENT_TEST. The debounce lives in send_operator_alert (its debounce_s window),
    keyed by `prospector:tick_digest` so a fresh tick ALERT path still pages immediately.
    """
```

Wire it at the same six sites as `_emit_tick_alerts`. The `tick` dict is already in scope.

### NEW — `tests/unit/test_status_snapshot.py`
Coverage:
- Reading an empty `store/` returns `daemon.pid=None` and `last_tick=None`, never raises.
- A heartbeat.json with `phase=generating, ts=now-30s` → `daemon.last_tick_age_s ~ 30`.
- A last ticks.jsonl row with `dry_run=True` and `result=None` is skipped; the prior
  substantive row is returned in `last_tick`.
- `spend` is read from `prospector.jsonl` rows with `event=spend` (or the existing
  `gating-decision` shape — pick whichever `run_scheduled.py:158` already uses).
- `providers.moat_blind` is True iff `provider_health.json` shows every moat brain dead.
- `alerts.active` is the `_active` dict from `alert_state.json` (values only).
- `backlog.deferred` and `backlog.provisional` are the glob counts from `store/dossiers/`.
- `format_status_snapshot({...})` is one string, ≤ 600 chars.

### NEW — `tests/unit/test_tick_digest.py`
Coverage:
- `_emit_tick_digest` is a no-op (no Telegram send) when `PYTEST_CURRENT_TEST` is set.
- A stubbed `send_operator_alert` is called exactly once per `_emit_tick_digest` invocation
  with `debounce_key="prospector:tick_digest"` and `debounce_s=7200.0`.
- `_emit_tick_digest` swallows every exception from `send_operator_alert` (the test asserts
  the daemon does not crash; pattern: `mock.patch` raising, then assert no exception).
- A second `send_operator_alert` call within 2h is suppressed by the debounce file in
  `~/.hermes/logs/.alert-debounce.json` (mirrors the `_debounced` test in `estate_alert.py`).

## 2. Acceptance criteria

Engine exit code 0 from:
```bash
cd /Users/chidionyema/Documents/code/prospector/.worktrees/feat-now-telegram-status-digest
.venv/bin/python -m pytest -q tests/unit/test_status_snapshot.py tests/unit/test_tick_digest.py
.venv/bin/python -m pytest -q
```

The new module is importable from a CLI invocation:
```bash
.venv/bin/python -c "from prospector.scheduler.status import status_snapshot, format_status_snapshot; print(format_status_snapshot(status_snapshot(None)))"
```
prints a sane one-line summary (with a `None` cfg it must raise the same way other paths
do — see §3; the comma is on the *function signature*, the test exercises it with a real cfg).

## 3. Risks / pins

- **Reading live store.** `status_snapshot(cfg)` calls `store_dir(cfg)` from
  `prospector/scheduler/paths.py:64` — that raises on a cfg without `store_dir`. Tests must
  pass `store_dir=tmp_path` (the same fence the paths module documents).
- **The dry-run noise.** `ticks.jsonl` contains both real tick rows and dry-run gating rows
  (cf. `hermes-cron-writes-dry-run-tick-rows.md`). The last-tick selector MUST filter by
  `dry_run != True` AND `result is not None` (dry-run gating rows have `result=None`).
- **Snapshots must be JSON-safe.** No `Path`, `datetime`, `Enum`, set, or `attrs`/`dataclass`
  instances. `isoformat()` on timestamps, `asdict`-like flattening for nested alerts.
- **No new dependencies.** Everything reads from files the existing modules already read.
- **No new on-disk state.** `status_snapshot` is purely read. Debounce state lives in the
  existing `~/.hermes/logs/.alert-debounce.json` written by `estate_alert.py`.
- **Founder-fence untouched.** The moat ruling path is not modified. The DAG moat
  (CLAUDE.md §3) is consumer-only here — we read `_active` and `audit/<date>.jsonl`, never
  write.

## 4. Out of scope (Hermes side, separate repo)

The `🎛 Now` button renderer in `~/.hermes` is not on this branch. When it lands, it should
either:
- Reuse `status_snapshot()` via `importlib.util.spec_from_file_location` (same pattern as
  `estate_alert.py` in `alerts.py:296`), OR
- Read `store/scheduler/last_digest.json` (a future cache — NOT introduced here).

This branch ships the engine data; the Hermes renderer is a follow-up against the Hermes repo.
