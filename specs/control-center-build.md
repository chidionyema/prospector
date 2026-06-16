# Control Center Build Spec

**Author:** Claude (Architect)
**Date:** 2026-06-16
**Status:** Build spec — implementation follows
**Ref:** `docs/CONTROL_CENTER_SPEC.md` (source of truth for design decisions)

---

## What exists now

- **`docs/CONTROL_CENTER_SPEC.md`** — the complete design spec (read this first; do not contradict it)
- **`prospector/report.py`** — G1 done: `catalogue_data`, `metrics_data`, `generation_quality_data`, `trend_data`, `costs_data` all return structured dicts. Existing print functions preserved for CLI.
- **`prospector/diagnostics.py`** — G1 done: `diagnostics_data(store, cfg)` returns `{alarms, latest_golden, golden_trend}`. `run_diagnostics(store, cfg)` is the print variant. Existing functions preserved.
- **`prospector/store.py`** — SQLite index + JSON files already on disk at `store/`
- **`store/prospector.db`** — 367 dossiers indexed
- **`store/provider_health.json`** — current provider circuit state
- **`store/golden_runs/*.json`** — 74 golden run files with discrimination trends

---

## What to build

Create `prospector/control_center/` with 7 pages + shared infrastructure.

### Directory layout

```
prospector/control_center/
  __init__.py
  app.py                    # streamlit entrypoint; st.navigation routing
  state.py                  # session_state keys + job registry helpers
  readers.py                # pure read funcs over store/ + config.yaml (st.cache_data)
  runner.py                 # subprocess job manager (launch/cancel/stream run.py)
  config_editor.py          # staged config edits with diff + golden veto
  components/               # shared widgets
    __init__.py
    dossier_card.py         # dossier header + verdict panels per check
    source_list.py          # cited sources with retrievable URLs
    gate_badge.py           # decision badge (PASS/KILL/DEFER)
    kpi_strip.py            # Overview KPI cards
  pages/
    __init__.py
    _overview.py            # §3.1
    _catalogue.py           # §3.2
    _launcher.py            # §3.3
    _diagnostics.py         # §3.4
    _parameters.py          # §3.5
    _reports.py             # §3.6
    _resume.py              # §3.7
```

Launch: `streamlit run prospector/control_center/app.py --server.port 8601`

---

## Phase 1 (read-only, zero risk)

Build `_overview.py`, `_catalogue.py`, `_reports.py`, `_diagnostics.py` using only the
read-plane (`readers.py`). No subprocess spawning, no config writes. Ships behind the
existing test/golden discipline.

### readers.py

Pure read functions (no side effects, no model calls). All use `st.cache_data(ttl=N)`:

| Function | Returns | TTL |
|---|---|---|
| `load_config_typed()` | `prospector.config.Config` | 10s |
| `catalogue_index()` | list of dicts from `prospector.db` | 10s |
| `load_dossier(id, decision)` | parsed `store/dossiers/<id>.<decision>.json` | 10s |
| `load_pending_signals()` | list of `signals/pending/*.json` parsed | 5s |
| `load_jobs()` | list from `store/control_center/jobs.json` | 5s |
| `load_provider_health()` | parsed `store/provider_health.json` | 5s |
| `load_audit_log()` | list of dicts from `store/prospector.jsonl` | 5s |
| `load_golden_runs()` | sorted list from `store/golden_runs/*.json` | 30s |
| `load_config_history()` | list from `store/control_center/config_history.jsonl` | 30s |

Graceful degradation: every function catches `FileNotFoundError` / `json.JSONDecodeError`
and returns an empty result rather than crashing.

### _overview.py (Cockpit)

- KPI strip via `st.metric` with color delta:
  - `# PASS / # KILL / # DEFER / # provisional` (from `catalogue_index()`)
  - `Today: runs launched, candidates processed` (from `load_jobs()` + today filter)
  - `Spend $ vs daily_cap_usd` progress bar (from `load_audit_log()` + `load_config_typed()`)
  - Moat status: from `load_provider_health()` — show circuit state per operator
  - Last golden discrimination score + pass/fail (from `load_golden_runs()`)
  - Pending queue depth + DEFER count (from `catalogue_index()` WHERE decision=defer + `load_pending_signals()`)
- Recent runs panel: last 10 from `load_jobs()` — status badge, elapsed, click → log
- Active alarms: from `prospector.diagnostics.diagnostics_data()` → `alarms`
- Moat-down banner: red `st.error` if both Claude+Gemini are `dead_until > now` in `load_provider_health()`
- Refresh: `st.fragment(run_every="10s")` on KPI strip + active runs only

### _catalogue.py (Dossier browser)

List view:
- `st.data_editor` or `st.dataframe` over `catalogue_index()` filtered by decision, lane,
  gate_fired, structural_form, provisional, composite range, free-text title search
- Column config: decision badge (`gate_badge`), composite as progress bar, published ✓
- Sort: composite (default desc), date (created_at), adversarial_confidence

Drill-in on row select:
- Call `load_dossier(id, decision)` → render via `dossier_card.py`
- Header: title, one-liner, lane, gate badge, composite + per-axis scores
- Verdict panel per check: verdict (SUPPORTED/REFUTED/UNVERIFIABLE), confidence,
  **cited sources** with URLs → via `source_list.py`
- Adversarial pass result + confidence
- "Re-vet this candidate" button (stage intent, don't launch yet — delegate to launcher)
- "Open raw JSON" in `st.expander`

### _reports.py (Reports & Economics)

- **Economics:** from `prospector.report.costs_data()` → total_spend, per-provider table,
  tokens, slowest ops. `st.metric` for totals; `st.line_chart` for spend-over-time.
- **Throughput/Metrics:** from `prospector.report.metrics_data()` → kill rate,
  per-lane table, gate dominance bar chart.
- **Generation quality:** from `prospector.report.generation_quality_data()` →
  form diversity, audience spread, prescreen rate, warnings.
- **Trend:** from `prospector.report.trend_data()` → rolling 7/30/90d cohort cards.
- **No write operations.** May show a "suggested" banner but cannot apply a change.

### _diagnostics.py (Diagnostics & Calibration)

- **Calibration alarms:** from `prospector.diagnostics.diagnostics_data()` → `alarms`.
  Render with severity badges + "what this means" note + link to Parameters page.
- **Golden-set:** from `diagnostics_data()["latest_golden"]` → discrimination score,
  pass/fail vs floor, per-case table.
  - "Run golden regression" button → launches `pytest tests/ -k golden` as a job.
  - "Run golden promotion" button → launches `python -m prospector.golden --operator …` as a job.
- **Golden trend sparkline:** from `diagnostics_data()["golden_trend"]` → `st.line_chart`
  of discrimination over time.
- **Operator health:** from `load_provider_health()` → per-operator latency, circuit state,
  `dead_until` countdown. "Probe operators" button → delegates to `_launcher.py`.
- **No write operations** (diagnostics runs are handled by runner jobs).

---

## Phase 2 (actuate)

### runner.py

Subprocess job manager for `run.py` invocations:

```
Job = {job_id, pid, argv, start_ts, status, log_file}
Status: queued | running | succeeded | failed | cancelled | deferred
```

Methods:
- `launch(argv: list[str]) -> job_id` — spawns `run.py` as a subprocess with line-buffered
  pipes, writes `<job_id>.log` to `store/control_center/runs/`, registers in `jobs.json`
- `stream(job_id) -> list[str]` — returns the last N lines from the ring buffer + on-disk log
- `cancel(job_id)` — SIGTERM → wait 5s → SIGKILL; marks job `cancelled`
- `reap_all()` — checks PIDs in `jobs.json`; dead PIDs → `unknown` status
- `get(job_id) -> Job | None`

Concurrency: `launch()` blocks if a job with status `running` already exists (single-actuator
lock). Raises `RuntimeError("A run is already in progress")`.

Job metadata persisted to `store/control_center/jobs.json` so history survives a Streamlit
restart.

Ring buffer: in-memory last 2,000 lines per job in a `st.cache_resource` singleton.
Full log always on disk + downloadable.

### _launcher.py (Run Launcher)

Tab per command (vet / signal / generate / discover). Form fields sourced from `run.py`
argparse. Common controls: scope estimate, dry-run / fixtures toggle, `--publish` gated
per spec §3.3.

On submit:
1. Call `runner.launch(argv)` — raises `RuntimeError` if a run is already running
2. Switch view to run-detail: auto-scrolling log via `st.fragment(run_every="2s")`,
   status badge, elapsed time, spend counter (parse from on-disk log or audit log).
3. Cancel button → `runner.cancel(job_id)`
4. On completion: summary card + deep-link to new dossier in Catalogue.

### _resume.py (Resume & Queue)

- **Pending signals:** from `load_pending_signals()` → table with "retry" per row +
  "Resume all" button → `runner.launch(["python", "-m", "prospector.run", "generate", "--resume"])`
- **DEFER queue:** query `catalogue_index()` WHERE decision="defer" → table.
  "Re-vet all" button → `runner.launch(["python", "-m", "prospector.run", "vet", "--resume"])`.
  **Disabled while moat is down** (show moat-down tooltip).
- **Run history:** from `load_jobs()` → all jobs with status, argv, duration, cost, log link.

---

## Phase 3 (parameters + golden veto)

### config_editor.py

Safe config editing utilities:

- `load_config_staged() -> dict` — load current config.yaml as dict into session_state
- `diff(old: dict, new: dict) -> str` — unified diff old→new (for display before write)
- `validate_config(cfg: dict) -> (ok: bool, errors: list[str])` — validates types, ranges,
  weights sum to 1.0, lane shape (the schema — no schema file yet; implement inline)
- `write_config(cfg: dict) -> None` — writes timestamped backup, then writes config.yaml
  with proper round-trip (preserve comments/YAML structure as much as possible using
  `ruamel.yaml` if available, else `pyyaml`)
- `mtime_changed(path, orig_mtime) -> bool` — detect concurrent external edits
- `moat_affecting_keys() -> set[str]` — returns config keys that affect the moat
  (hard gates, confidence_floor, moat operator routing). Hardcoded set matching spec §3.5.
- `certification_status() -> dict` — reads `store/control_center/certification.json`
  (created on first golden pass after a moat-affecting edit)

### _parameters.py (Parameters page)

Grouped, typed controls mapped to config keys. **No raw-YAML-only editing** by default.

Groups: Thresholds, Hard Gates, Weights, Retrieval Resilience, Operator Routing,
Generation, Ambition Lanes, Spend Guard.

Safety mechanics:
1. Edits staged in `st.session_state`, written on "Save changes" only
2. Before write: show `st.code(diff(...))` unified diff
3. Save: write backup first, validate, refuse on validation failure
4. Moat-affecting edit: mark config "uncertified" in `certification.json`, show banner
   "Golden re-run required to certify" on Overview
5. On mtime conflict: refuse to overwrite + show 3-way diff

Raw YAML view in an expander for power users.

---

## Acceptance criteria

| # | Criterion | Verification |
|---|---|---|
| AC1 | All 194 existing tests still pass after changes | `pytest -q` exit 0 |
| AC2 | `streamlit run app.py` launches on port 8601 with no import errors | manual |
| AC3 | Overview page renders KPI strip without crashing on empty store | empty-store state |
| AC4 | Catalogue drill-in renders a dossier with cited sources visible | pick one dossier |
| AC5 | Launching a run shows live log streaming in the UI | start a `vet --fixtures` run |
| AC6 | Cancelling a run marks it `cancelled` in `jobs.json` | check file |
| AC7 | Parameter save writes a backup before overwriting | check `config.yaml.bak.*` |
| AC8 | Parameter save blocks when weights sum ≠ 1.0 | try it |
| AC9 | Publish checkbox is disabled when golden is stale/never run | state machine |
| AC10 | E1 (moat down) shows red banner and disables re-vet buttons | mock `dead_until=0` |

---

## Files to protect from Builder mutation

- `tests/` (entire directory)
- `prospector/report.py` (G1 already done)
- `prospector/diagnostics.py` (G1 already done)
- `prospector/run.py` (no changes)
- `prospector/verify.py`, `prospector/kill_filter.py` (founder fence)
- `config.yaml` (only modified via the config_editor write path)
- `store/` (read-only except `store/control_center/`)
