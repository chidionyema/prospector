# Spec — `feat/prospector-now-on-telegram` (Hermes side)

> **Hermes side** of the "running blind" wire-up. The engine side (status_snapshot +
> tick digest pusher) is already on `feat/now-telegram-status-digest` in the prospector repo
> with 17/17 fail-then-green tests. This branch ships the consumer: a `🎛 Now` button that
> calls the engine's `status_snapshot()` and renders it as a panel.
>
> Worktree: `~/.hermes/.worktrees/feat-prospector-now`
> Branch: `feat/prospector-now-on-telegram` (off `main` @ `7c25eff09d`,
>         upstream of `cf262aa2e9` / `2cf037ee4f` — the local cockpit feature work)
> Verify: `python -m pytest -q` (final); `python -m pytest -q tests/gateway/operator_shell/test_prospector_now.py` (gate)
> Note: the worktree has no `.venv` of its own — the user's anaconda3 env (`python` on PATH)
>       matches the submodule's tests. Use `python -m pytest` directly from the worktree root.
> Note: other agents are working in the submodule's `main` branch (15 files dirty: cron,
>       estate.py, menu.py, hermes_cli/*, brains.py). My worktree is on a fresh branch
>       `feat/prospector-now-on-telegram` and the dirty state is in the parent worktree at
>       `/Users/chidionyema/.hermes/hermes-agent/`. The builder MUST NOT touch the parent
>       worktree's dirty state — only edit files in the new worktree.

## 0. Why this exists

The engine emits a structured stream of state (heartbeat, last tick, spend, provider health,
active alerts, backlog) via `prospector/scheduler/status.py::status_snapshot`. The engine
already pushes one Telegram message per tick (after every `_emit_tick_alerts` site). But:

- The per-tick digest is debounced 2h — the operator sees a snapshot when the engine is alive.
- If the engine is **silent**, the operator has no way to ASK what's happening from the phone.
- The Telegram mission card (`gateway/operator_shell/mission.py`) shows Hermes state
  (daemons, cron, missions, spend) — not the engine's state.

The `🎛 Now` button is the on-demand counterpart to the per-tick digest. It is where the
founder answers "what is the engine doing right now?" with one tap from the phone.

## 1. Files

### NEW — `gateway/operator_shell/prospector_now.py`
A pure read-only renderer. Surface:

```python
def render_prospector_now() -> tuple[str, list[list[tuple[str, str]]]]:
    """Render the engine's status_snapshot() as a Telegram message with action buttons.

    Returns (text, button_rows). The text is the digest + a small severity legend.
    The buttons lead BACK to the engine's tooling (daemon, params, cron) so the operator
    can act on what the digest shows.

    The engine's `status.py` is loaded path-based from the live checkout — the same
    pattern the engine uses to load `~/.hermes/scripts/estate_alert.py` in reverse
    (`prospector/scheduler/alerts.py:296-357`). The path is resolved via env var
    `PROSPECTOR_REPO` then `~/Documents/code/prospector` then `prospector` on sys.path.
    The renderer is fault-tolerant: a missing engine module degrades to a one-line
    "engine unreachable" — it never raises into the cockpit.
    """
```

Reads from the engine's `status_snapshot()`:
- `daemon.phase`, `daemon.last_tick_age_s`, `daemon.pid`
- `last_tick` (dossiers/passes/kills/defers/cost)
- `spend` (today / cap / subscription)
- `providers.moat_blind`, `providers.dead`
- `alerts.active_count` (first title only)
- `backlog.deferred`, `backlog.provisional`

Plus a severity legend (🟢/🟡/🔴) computed from the snapshot — same convention as
`status_summary.py:177-228` and `panel_chrome.py:LEGEND`.

### MODIFY — `gateway/operator_shell/estate.py`
Add a single entry to `_PANELS` (the registry that `test_every_button_dispatches.py`
asserts is exhaustive):

```python
# Engine readout — the operator's "what is the factory doing?" tap. The data
# pipeline is `prospector/scheduler/status.py::status_snapshot()` (engine repo
# branch `feat/now-telegram-status-digest`). The engine also pushes a debounced
# digest after every tick; this is the on-demand counterpart.
"prospector_now": ("prospector_now", "render_prospector_now", "Now", _ARG_NONE),
```

No other edits to `estate.py`. The renderer does not need to be in `OPERATOR_TELEGRAM_MENU`
because the button is rendered on the mission card itself (see §2).

### MODIFY — `gateway/operator_shell/mission.py`
Add ONE button to the mission card (the persistent pinned card). The button is the
default location because the mission card is the operator's home — every tap on the
home card discovers the engine readout without leaving home.

```python
# 🎛 Now — the engine readout. One tap to `status_snapshot()`. The data is the
# same per-tick digest the engine pushes automatically, but on demand.
# (orchestrates the connection to the engine repo above.)
```

The renderer for the button lives in `prospector_now.py`; the button emission is
in `mission.py` (it owns the card layout). The button text is `🎛 Now` with callback
`estate:prospector_now`.

### NEW — `tests/gateway/operator_shell/test_prospector_now.py`
Coverage (the gate):
- `render_prospector_now()` returns `(text, buttons)` even when the engine module is
  absent (the engine-side module is on a branch not yet merged; the test must not
  require the engine to be installed).
- The on-error path emits a one-line "engine unreachable" message — never raises.
- The renderer maps the engine's snapshot onto the same 🟢/🟡/🔴 legend as
  `status_summary.py` (one assertion per status: green healthy moat, yellow when
  any provider dead, red when moat blind).
- The mission card now has a button whose `callback_data` starts with `estate:prospector_now`
  (asserted by reading the rendered card text — the test_every_button_dispatches
  greedy regex will catch it once the button is wired).
- The `_PANELS` registry in `estate.py` contains a key for `prospector_now` (import
  the registry and assert membership).
- The integration check: when `status_snapshot()` is monkey-patched to a known good
  snapshot, the rendered text contains the digest content (e.g. "moat blind" or
  "alerts active" depending on which fixture).

### (No need to edit) `tests/gateway/operator_shell/test_every_button_dispatches.py`
That test is static and exhaustive — it will PASS once the `_PANELS` key is added
and will FAIL if the button is added without the registry entry. No edits here.

## 2. Acceptance criteria

Engine exit code 0 from:
```bash
cd /Users/chidionyema/.hermes/.worktrees/feat-prospector-now
.venv/bin/python -m pytest -q tests/gateway/operator_shell/test_prospector_now.py
.venv/bin/python -m pytest -q tests/gateway/operator_shell/test_every_button_dispatches.py
.venv/bin/python -m pytest -q
```

The new renderer is importable from a CLI invocation:
```bash
.venv/bin/python -c "from gateway.operator_shell.prospector_now import render_prospector_now; print(render_prospector_now()[0])"
```

prints either "Prospector" digest (engine reachable) or a one-line "unreachable" warning
(engine not on disk yet). Both are valid; the test makes the contract explicit.

## 3. Risks / pins

- **Engine path resolution.** The engine lives at `~/Documents/code/prospector`. The
  renderer MUST NOT hard-fail if the engine is in a worktree, on a different branch, or
  missing entirely. Resolution order: `PROSPECTOR_REPO` env var → `~/Documents/code/prospector`
  → `importlib.util` against the first `prospector.scheduler.status` importable on `sys.path`.
  The test for the missing case is the cleanest assertion.
- **No subprocess.** The renderer must NOT shell out to the engine (no `prospector run`
  invocation). It reads only `status_snapshot()` and `format_status_snapshot()`. The
  engine's own daemon is the producer; the renderer is a pure read-only consumer.
- **Path-based import is hermetic.** The engine module is loaded via `importlib.util
  .spec_from_file_location` so the Hermes venv doesn't need the prospector package
  installed. This mirrors the engine's `estate_alert.py` loader.
- **No new dependencies.** Use only stdlib + already-imported modules.
- **No new on-disk state.** The renderer reads existing files only.
- **Founder-fence untouched.** No money rail, no Stripe, no `verify.py`/`bridge.py`/`pricing.py`.
- **No venv to install.** The submodule's existing tests run under the parent Python
  (`/usr/local/bin/python3.11` or similar); the worktree has no `.venv` of its own. The
  builder must use the same Python the rest of the submodule's tests use.
- **The `test_every_button_dispatches` test is the silent gate.** It will fail at
  runtime if the mission card emits a `estate:prospector_now` button without the
  `_PANELS` entry, and pass once both are wired. That is the contract.

## 4. What this does NOT do (out of scope)

- The engine-side `status_snapshot()` and `_emit_tick_digest()` are already on
  `feat/now-telegram-status-digest` — this branch does not modify them.
- The persistent reply keyboard (P1 of `OPERATOR_UX_SPEC.md`) is not on this branch.
  This adds ONE button to the mission card; the persistent keyboard is a separate
  spec covering all five intent buttons.
- The deep-link from the engine's live daemon into Hermes (heartbeat → Hermes) is not
  on this branch. The engine's `send_operator_alert` push is already debounced; the
  on-demand /probe path lives here.
- The 13 per-role model picker (the unbuilt P2 of `OPERATOR_UX_SPEC.md`) is not on
  this branch.
