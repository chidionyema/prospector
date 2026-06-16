# Prospector Control Center — Design & Specification

**Status:** Draft v1 (design/spec only — no implementation)
**Author:** Claude (Opus 4.8), 2026-06-16
**Reference model:** `~/Documents/code/signalengine/dashboard/app.py` (Streamlit, read-only telemetry)
**Targets:** the Prospector engine (`prospector/`, `run.py`, `config.yaml`, `store/`, `signals/`)

---

## 0. Why this exists

Today the engine is driven entirely from the CLI: run `python run.py vet …`, then `cat` a
dossier JSON, then hand-edit `config.yaml`, then re-run, then `python run.py report`. That loop
is correct but clunky — the operator context-switches between a terminal, a JSON viewer, and a
YAML editor, and there is no single place that shows *what the engine is doing right now, what it
has produced, and what is mis-calibrated*.

The Control Center collapses that loop into one local Streamlit app: **launch runs, watch them
live, browse every dossier with its cited sources, read the diagnostics/economics, and tune
parameters — safely — without leaving the screen.**

It is an **operator console**, not a public product. It runs locally, single-user, under the
existing Claude Code subscription model. It adds **zero** new hosted infrastructure (consistent
with the repo rule "No hosted service / no API-key calls beyond this repo").

---

## 1. What we inherit from signalengine — and where we deliberately diverge

The signalengine control center (`dashboard/app.py`, 899 lines) is a clean reference. Patterns we
copy verbatim:

| Pattern | signalengine source | We reuse it for |
|---|---|---|
| `st.set_page_config(layout="wide")` + KPI metric strip | app.py:18–22, 597–721 | Overview header |
| `st.fragment(run_every=…)` for scoped auto-refresh | app.py:888–896 | Live run-log + queue pages only |
| Graceful degradation — every loader returns empty on missing file/err | app.py:62, throughout | Every store reader |
| Rich `st.column_config` formatters (currency/percent/progress) | app.py:780–803 | Catalogue + economics tables |
| `st.cache_data(ttl=…)` for cheap repeated reads | app.py:218 | dossier index, config load |
| Read-the-artifact-not-reconstruct (read `venue_state.json`, not replay ledger) | app.py:260–293 | read `store/prospector.db` + dossier JSON, never recompute verdicts |

**The critical divergence:** signalengine's dashboard is **pure read-only telemetry** — it never
triggers the daemon, never edits parameters (app.py:508–524 are display-cadence controls only).
Prospector's operator explicitly needs to **(a) launch runs and (b) tweak parameters and rerun**.
So our Control Center is **read + write + actuate**, which forces three things signalengine never
had to solve:

1. **A job/process model** (runs are long, cost money, and can hit the usage cap).
2. **Safe parameter editing** (a careless gate edit can silently break the moat).
3. **Concurrency & the truth/demand firewall** (the UI must not let a demand-driven tweak bypass
   the golden-set veto — see §6.3).

---

## 2. Architecture & process model

### 2.1 Component layout

```
prospector/
  control_center/
    app.py                # Streamlit entrypoint; tabs/pages router
    runner.py             # subprocess job manager (launch/stream/cancel run.py)
    readers.py            # pure read funcs over store/ + config.yaml (cached)
    config_editor.py      # load/validate/diff/write config.yaml safely
    components/           # shared widgets (dossier card, source list, gate badge)
    state.py              # session_state keys + job registry helpers
```

Launch: `streamlit run prospector/control_center/app.py --server.port 8601`
(8601 to avoid colliding with signalengine's 8501).

### 2.2 Two data planes

**Read plane (synchronous, in-process).** The UI imports `readers.py`, which reads the engine's
*artifacts* directly — never re-runs engine logic, never makes LLM/retrieval calls. Sources:

| Artifact | Path | Used by |
|---|---|---|
| Dossier index (fast queries) | `store/prospector.db` (SQLite: candidate_id, title, decision, gate_fired, composite, ambition_tier, structural_form, provisional, dense_reward, adversarial_confidence) | Catalogue, Overview |
| Full dossiers | `store/dossiers/<id>.<decision>.json` | Dossier drill-in |
| Audit log | `store/prospector.jsonl` (JSONL: tokens, cost, latency per run) | Economics, Reports |
| Provider health | `store/provider_health.json` (`{op: {dead_until, dead_for_s}}`) | Operators page |
| Golden-set runs | `store/golden_runs/<operator>_<ISO>.json` (discrimination score, cases) | Diagnostics |
| Listings | `store/listings/<id>.json` | Catalogue (published badge) |
| Pending signals | `signals/pending/<key>.json` | Resume/Queue |
| Config | `config.yaml` | Parameters |

The read plane reuses the **existing report/diagnostic code** rather than re-implementing it:
`report.py` (catalogue/metrics/costs/quality/trend), `diagnostics.py` (calibration alarms +
golden-set), and the operator-probe logic from `run.py _cmd_operators()`. The UI calls these as
library functions and renders their structured output. Where they only print today, we add a thin
"return the data, then print" seam so the UI and CLI share one source of truth (no logic fork).

**Write/actuate plane (asynchronous, out-of-process).** Runs are launched as **subprocesses of
`run.py`**, not by importing the engine into the Streamlit process. This is the load-bearing
decision — rationale:

- **Isolation of cost & blast radius.** A run can hit the daily spend cap (`spend_guard.daily_cap_usd`,
  config ~line 380) or the Claude Code usage cap. A crash, hang, or `ProviderExhaustedError`
  must not take down the console.
- **Cancellation.** A subprocess can be killed (SIGTERM) cleanly; an in-process engine call on
  Streamlit's thread cannot be interrupted.
- **Live progress for free.** `progress.py` already emits step/note/result/summary banners to
  stderr. We stream the child's stdout+stderr line-by-line into the UI — no new telemetry channel.
- **Honest concurrency.** The engine already bounds itself (`retrieval.vet_workers`,
  circuit breakers). The console just needs to ensure it doesn't launch two competing runs (§6.2).

`runner.py` responsibilities: build the argv from a form, `subprocess.Popen` with line-buffered
pipes, register the job in a process-wide registry (PID, argv, start time, status, log buffer,
log file path), stream output into a ring buffer + tee to `store/control_center/runs/<job_id>.log`,
expose `cancel(job_id)` (SIGTERM → SIGKILL escalation), and reap exit codes.

### 2.3 Job lifecycle & persistence

A job = one `run.py` invocation. States: `queued → running → (succeeded | failed | cancelled |
deferred)`. `deferred` is first-class: it maps to the engine's DEFER-on-moat-exhaustion outcome
(`run.py` ~198–211, gate `moat_exhausted`) — the run "succeeded" mechanically but produced a
DEFER, so it surfaces in the Resume/Queue page, not as a failure.

Job metadata is persisted to `store/control_center/jobs.json` so the history survives a Streamlit
restart (Streamlit session_state is per-browser-session and ephemeral). The **live log buffer**
lives in a module-level registry guarded by `st.cache_resource` (singleton across reruns); the
**durable log** is the on-disk `<job_id>.log`. On app restart, in-flight subprocesses are
detected by re-reading `jobs.json` + checking PIDs are alive; orphaned PIDs are marked `unknown`.

---

## 3. Page-by-page specification

Seven pages, left-nav (`st.sidebar` radio or `st.navigation`). Each page lists: purpose, data
sources, controls, and what it writes.

### 3.1 Overview (Cockpit)

**Purpose:** one-glance health + activity. The "is the engine alive and producing?" screen.

**KPI strip** (`st.metric`, color deltas):
- Catalogue: # PASS / # KILL / # DEFER / # provisional (from `prospector.db`).
- Today: runs launched, candidates processed, spend $ vs `daily_cap_usd` (progress bar), kill rate.
- Moat status: Claude/Gemini circuit state (closed/open/half-open) from `provider_health.json`.
- Non-critical chain status: DeepSeek→MiniMax→Gemini-flash health.
- Last golden-set discrimination score + pass/fail vs `--floor` (from latest `golden_runs/`).
- Pending queue depth (`signals/pending/` count) + DEFER count.

**Panels:** recent runs (last 10 from `jobs.json`, status badges, click → run detail); active
alarms (mirror `diagnose` no-flag calibration alarms: zero-yield, single-gate dominance, dead
gates); a "moat down" banner (`st.error`) when both Claude+Gemini are exhausted.

**Refresh:** `st.fragment(run_every="10s")` on the KPI strip + active-runs panel only.

**Writes:** none.

### 3.2 Catalogue (Dossier browser)

**Purpose:** replace `cat store/dossiers/*.json` and `report --catalogue`. Browse, filter, and
**drill into the full grounded receipt** for any candidate — PASS *and* KILL (KILL is first-class
per CLAUDE.md; the kill log is the proof the filter is real).

**List view:** `st.dataframe` over `prospector.db` with filters (decision, lane/ambition_tier,
gate_fired, structural_form, provisional flag, composite range, free-text title search) and sort
(composite, date, adversarial_confidence). Column config: decision badge, composite as progress
bar, published ✓ if a `listings/<id>.json` exists.

**Drill-in (the important part):** select a row → render the full dossier from
`dossiers/<id>.<decision>.json`:
- Header: title, one-liner, lane, decision badge, gate that fired, composite + per-axis scores.
- **Verdict panel per check** (pain_reality, value_durability, incumbency, payer_solvency,
  distribution, legality): the verdict (supported/refuted/unverifiable), confidence, and the
  **cited sources with retrievable URLs** — this is the source-or-die contract made visible.
  Any claim marked `unverifiable` is shown as such, never dressed up.
- Adversarial pass result + confidence.
- Secondary artifacts (PASS only): build spec, GTM, ops, financial model, claim-checked marketing.
- Provenance footer: provider_chain + per-check provider (which model grounded each verdict),
  cost, timing — straight from the dossier/audit log.

**Actions:** "Re-vet this candidate" (→ launches `vet --resume`-style re-run, §3.7); "Open raw
JSON" (`st.expander` with `st.json`); for DEFER, a "retry now" shortcut.

**Writes:** none directly (re-vet delegates to the runner).

### 3.3 Run Launcher

**Purpose:** replace hand-typed `run.py vet|signal|generate|discover`. Form-driven launch with a
live log, so "tweak a param → rerun → watch" is one screen.

**Sub-tabs, one per command** (flags sourced from `run.py` argparse ~1228–1396):

- **Vet** — `--title`, `--one-liner`, `--why-now`, `--lane`, `--operator`, `--fixtures` (offline
  toggle), `--publish` (guarded — see below).
- **Signal** — `--text` or `--file` (file picker / textarea), `--count`, `--lane`, `--profile`,
  `--focus`, `--operator`, `--publish`.
- **Generate** — `--candidates`, `--exploration` (slider 0.2–0.9), `--lane`, `--profile`,
  `--focus`, `--publish`.
- **Discover** — `--signals`, `--sectors`, `--count`, `--dry-run`, `--no-save`, `--lane`,
  `--publish`.

**Controls common to all:** an "Estimated scope" hint (candidates × checks) and a **dry-run /
fixtures preference banner** so the operator can rehearse offline before spending. The `--publish`
checkbox is **double-gated**: it is disabled unless (a) a recent golden-set run passed the floor
and (b) the operator ticks an explicit "I reviewed, publish on PASS" confirm — publication is the
one irreversible, outward-facing action (it hits Paddle + R2 + the live catalog via `bridge.py`).

**Launch → live log:** on submit, `runner.py` spawns the subprocess; the page switches to a
**run-detail view** with an auto-scrolling log (`st.fragment(run_every="2s")` tailing the ring
buffer), a status badge, elapsed time, a live spend counter (parsed from the audit log / progress
banners), and a **Cancel** button. On completion: a summary card (decision, gate, source count,
cost, timing — the engine's step-8 summary) and a deep-link to the new dossier in the Catalogue.

**Writes:** spawns a `run.py` subprocess (which writes dossiers/audit/listings as usual). The
console itself writes only `jobs.json` + the job log.

### 3.4 Diagnostics & Calibration

**Purpose:** replace `diagnose`, `diagnose --deep`, and the golden-set workflow. This is the
**truth loop's** home — is the filter still discriminating, or has it drifted?

**Calibration alarms** (free, no API): render `diagnostics.py` (~47–93) output — zero-yield,
single-gate dominance, dead gates — with severity badges and a plain-English "what this means /
what to tune" note linking to the relevant control on the Parameters page.

**Golden-set (the veto):**
- Show the latest `golden_runs/<operator>_<ISO>.json` per operator: discrimination score,
  pass/fail vs floor, and the **per-case table** (which golden cases the chain got right/wrong on
  mixed-sector discrimination).
- "Run golden regression" button → launches `pytest -k golden` (offline, MockOperator+fixtures —
  cheap, proves prompts didn't regress) as a job.
- "Run golden promotion" button → launches `python -m prospector.golden --operator <x> --runs N`
  (online, real model+fixtures — proves discrimination ≥ floor before a model is trusted in the
  moat). Cost-gated like any paid run.
- A **trend sparkline** of discrimination over time (across `golden_runs/` files) so drift is
  visible, not just the latest point.

**Operator health** (from `provider_health.json` + `run.py _cmd_operators` ~949–1100): per-operator
latency, circuit state (closed/open/half-open), `dead_until` countdown, chain ordering for moat
vs non-critical. "Probe operators" button → launches `operators --timeout … [--gen]`.

**Writes:** none directly (everything delegates to jobs).

### 3.5 Parameters (config.yaml editor)

**Purpose:** replace hand-editing `config.yaml`. The highest-risk page — a bad gate edit silently
breaks the moat — so it is the most guarded (§6.3).

**Layout:** grouped, typed controls mapped to config keys (no raw-YAML-only editing as the
default, though a raw view is available in an expander for power use):

- **Thresholds** — `confidence_floor` (slider 0–1, default 0.6), `min_composite_to_pass`
  (number, default 3.2).
- **Hard gates** — per-check toggles for kill-on-`[refuted]` (pain_reality, value_durability,
  incumbency, payer_solvency, distribution, legality) + `adversarial_decisive` toggle.
- **Weights** — six axes (pain_acuity .20, money_provability .20, automatability .20,
  distribution .15, defensibility .15, build_feasibility .10) with a **live "must sum to 1.0"**
  validator and a normalize button.
- **Retrieval resilience** — provider chain order, `queries_per_check`, `results_per_query`,
  timeouts + escalation, `search_retries`, `vet_workers`, breaker threshold/cooldown.
- **Operator routing** — moat order (Claude→Gemini), non-critical chain order
  (DeepSeek→MiniMax→Gemini-flash), `model` / `model_fast`.
- **Generation** — `candidates_per_signal`, `structural_forms`, `audience_forms`,
  `controller.killrate_window`, `exploration_min/max`.
- **Ambition lanes** — per-lane `hard_gates`, `thresholds`, `adversarial_directive`,
  `structural_forms`; `active_lane` / `active_lanes`.
- **Spend guard** — `daily_cap_usd`, `warn_at_usd`.

**Safety mechanics (see §6.3):** edits are staged in `st.session_state`, not written on every
keystroke. A **diff view** (`st.code` unified diff old→new) is shown before any write. Saving:
- writes a **timestamped backup** `config.yaml.bak.<ts>` first (so any edit is reversible),
- validates the full doc against a schema (types, ranges, weights-sum, lane shape) and **refuses
  to write on validation failure**,
- if the edit touches a **moat-affecting key** (any hard gate, `confidence_floor`, prompts,
  operator routing into the moat), the save is marked **"requires golden re-run"** and the UI
  prompts to launch golden regression; the change is written but flagged *uncertified* on the
  Overview until a passing golden run clears it. This operationalizes "Golden-set regression
  gates all changes" without blocking iteration.

**Writes:** `config.yaml` (+ `.bak`), and a change-log entry to `store/control_center/config_history.jsonl`.

### 3.6 Reports & Economics

**Purpose:** replace `report --metrics|--costs|--generation-quality|--trend`. The demand/economics
view — **strictly walled off from the truth loop** (it informs *what to offer*, never *what may
ship*; see §6.3).

- **Economics:** lifetime + per-day spend (from `prospector.jsonl`), tokens, $/dossier,
  $/PASS, slowest ops, spend vs cap over time (line chart). Errors excluded from cost (matches
  `report --costs`).
- **Throughput/metrics:** kill rate, per-lane breakdown, **gate dominance** (which gate kills
  most — a calibration smell if one gate dominates).
- **Generation quality:** structural-form diversity, audience spread, prescreen pass rate.
- **Trend:** rolling 7/30/90-day cohorts (kill rate, gate mix, composite distribution).

**Writes:** none. **Note:** this page may *suggest* a parameter change (e.g., "incumbency kills
70% — consider reviewing") but cannot apply it; the operator must go to Parameters, where the
golden veto applies.

### 3.7 Resume & Queue

**Purpose:** replace `generate --resume` and `vet --resume`, and make the DEFER/pending backlog
visible (today it's invisible files under `signals/pending/`).

- **Pending signals** (`signals/pending/<key>.json`): table of signals whose generation chain was
  exhausted (DeepSeek→MiniMax→Gemini-flash all down). Per-row "retry" + a "Resume all
  generation" button → launches `generate --resume` (re-runs the pipeline; deletes the pending
  file on success — `run.py` ~846–898).
- **DEFER queue** (Decision.DEFER + provisional from `prospector.db`): candidates whose moat was
  exhausted at verdict time. "Re-vet all" button → launches `vet --resume` (re-vets when
  Claude+Gemini recover, overwrites DEFER with the fresh verdict — `run.py` ~680–761). A
  **moat-health gate**: the button is disabled with an explanatory tooltip while the moat is still
  down (no point re-vetting into an exhausted moat).
- **Run history:** all jobs from `jobs.json` with status, argv, duration, cost, log link.

**Writes:** delegates to runner; clears pending files via the engine's own resume logic.

---

## 4. Cross-cutting concerns

**State management.** Mirror signalengine's minimalism: `st.session_state` only for UI state
(selected dossier, staged config edits, active page). Durable state lives on disk
(`jobs.json`, `config_history.jsonl`) — never trust session_state to survive a rerun/restart.
`st.cache_data(ttl=…)` for read-plane loaders (short TTL, e.g. 5–10s, so fresh runs appear);
`st.cache_resource` for the singleton job registry and DB connection.

**Refresh.** Auto-refresh is **scoped** (`st.fragment(run_every=…)`) to only the live regions
(run log, Overview KPIs, queue), exactly as signalengine isolates its `_live_region`. Static
pages (Catalogue drill-in, Parameters) do **not** auto-refresh — refreshing a half-edited config
form would be hostile.

**Secrets.** API keys / provider creds stay where they already are (env / existing config), read
by the engine subprocess — the UI **never displays or edits secrets**. The Paddle/R2/Postmark
delivery creds (the store rail) likewise stay server-side. The console shows *health/state*, not
credentials.

**Audit.** Every actuation (run launched, config saved, publish confirmed) appends to
`store/control_center/actions.jsonl` (who/none-single-user, when, what argv/diff). This keeps the
"write every run to store/" + audit-trail discipline intact for UI-initiated actions too.

---

## 5. Edge cases & failure modes (explicitly requested)

| # | Edge case | Behaviour |
|---|---|---|
| E1 | **Moat down** (Claude+Gemini both exhausted) mid-run | Run returns DEFER (`moat_exhausted`); job marked `deferred`, candidate lands in DEFER queue; Overview shows red moat banner; re-vet buttons disabled until recovery. Never silently downgrade verdicts to the cheap tail. |
| E2 | **Non-critical chain down** (DeepSeek+MiniMax+Gemini-flash) during generation | Signal saved to `signals/pending/`; job ends with a "saved for resume" notice; appears in Resume page. No crash. |
| E3 | **Daily spend cap hit** mid-batch | Engine's spend guard stops; UI shows cap-reached banner, spend bar at 100%, remaining candidates left unprocessed and offered for resume. Launch forms warn when an estimate would exceed `warn_at_usd`. |
| E4 | **Two runs launched at once** | Runner enforces a single-active-heavy-run lock (configurable to N) — second submit is queued or blocked with a clear message; prevents the engine from competing with itself on `vet_workers`/budget. |
| E5 | **Streamlit restarts while a run is in flight** | `jobs.json` + live-PID check on boot: alive PIDs reattach (log tailed from on-disk `<job_id>.log`); dead PIDs marked `unknown`; no zombie state. |
| E6 | **Concurrent external edits to config.yaml** (another agent/editor — exactly the reverter problem seen with the store rail) | On save, compare on-disk mtime/hash vs the hash loaded into the form; if changed underneath, **refuse to overwrite** and show a 3-way diff. Never blind-clobber. |
| E7 | **Corrupt/partial dossier JSON** (run killed mid-write) | Reader catches parse errors per-file, shows the row as "⚠ unreadable" with the raw bytes in an expander, never crashes the Catalogue. |
| E8 | **`prospector.db` and `dossiers/` disagree** (index stale) | UI treats dossier JSON as truth, the DB as an index; a "reindex" action re-derives the DB from the JSON files. Mismatches flagged on Diagnostics. |
| E9 | **Weights edited to not sum to 1.0** | Save blocked; inline validator + one-click normalize. |
| E10 | **Gate/threshold edit that would break discrimination** | Saved but flagged *uncertified*; Overview shows "config uncertified — golden re-run required"; publish disabled until a passing golden run. |
| E11 | **Publish clicked but golden stale / never run** | Publish checkbox disabled with explanation; forces a golden pass first. Publication is the only irreversible outward action — gated hardest. |
| E12 | **Long log floods memory** | Ring buffer caps in-memory lines (e.g. last 2k); full log always on disk and downloadable. |
| E13 | **Cancel a run** | SIGTERM → grace period → SIGKILL; partial artifacts already written stay (idempotent re-run is safe); job marked `cancelled`. |
| E14 | **Empty store (cold start)** | Every page renders an empty-state with a "launch your first run" CTA rather than erroring — matches signalengine's empty-dict degradation. |
| E15 | **Fixtures/offline mode** | A global "offline (fixtures)" indicator; launch forms default `--fixtures` when offline so the operator can rehearse without spend or network. |

---

## 6. Hard constraints the design must honor

1. **§6.1 Source-or-die is visible, not assumed.** The dossier drill-in (§3.2) renders the cited
   sources for every check; `unverifiable` is shown as `unverifiable`. The UI never invents or
   smooths over a missing source. It is a *viewer* of grounded verdicts, never a producer of them.
2. **§6.2 Single-actuator concurrency.** The console must never let itself become a second rogue
   writer to the engine's files (the reverter pain, applied to ourselves). One heavy run at a
   time; config writes are mtime-guarded (E6); all writes are confined to `store/control_center/`
   plus the deliberate `config.yaml` edit.
3. **§6.3 The two loops never merge.** The Reports/Economics page (demand) is read-only and
   physically cannot apply a change. Any parameter change flows through the Parameters page, where
   a moat-affecting edit triggers the golden-set veto (E10/E11). Demand metrics may *inform*, but
   the truth loop's golden-set veto is the only gate to publication.
4. **§6.4 Moat purity.** The UI surfaces provider chains and lets the operator route models, but
   the engine still enforces that DeepSeek/MiniMax never run verdicts/adversarial passes. The
   console exposes no control that could route a cheap-tail model into the moat without it passing
   golden promotion first.
5. **§6.5 No new infra.** Local Streamlit, subprocess of the existing `run.py`, reads existing
   artifacts. No server, no DB beyond the existing SQLite, no API keys beyond the repo's.
6. **§6.6 Founder fence.** The Control Center is operator tooling; building it is normal
   engineering. But it must not weaken the fence — publish/Paddle/R2 actions remain explicit,
   confirmed, and golden-gated, never automated by the UI.

---

## 7. Known gaps & open questions (to resolve before build)

- **G1 — `report.py`/`diagnostics.py` print vs return.** The read plane needs these to *return*
  structured data. Today some only print. Small refactor (return-then-print seam) required so the
  UI and CLI don't fork logic. **Scope this first.**
- **G2 — Live spend during a run.** Spend is currently known after the fact (audit log). For the
  live spend counter we either parse progress banners or have `progress.py` emit a machine-readable
  spend event. Decide: parse stderr (no engine change) vs. add a structured progress channel.
- **G3 — Cancel semantics.** Confirm every `run.py` stage is safe to kill mid-write (idempotent
  re-run). Dossier writes appear atomic-ish; verify SalesAudit/listing writes (and bridge.py
  publish) have no half-committed state on SIGKILL.
- **G4 — Config schema.** There is no formal schema for `config.yaml` today; the Parameters page
  needs one (types, ranges, lane shape, weights-sum). Author it as `control_center/config_schema.py`
  (also usable as a standalone `run.py validate-config` CLI check).
- **G5 — Multi-operator / single-user.** Spec assumes single local operator (consistent with the
  repo's "supervised batches" model). If ever multi-user, the single-actuator lock and audit
  identity need real auth — out of scope for v1, noted so it isn't designed out.
- **G6 — Golden "certified" state storage.** Where does "config is certified by golden run X" live?
  Proposal: a `store/control_center/certification.json` linking the active config hash to the
  golden run that last passed on it; Overview reads it to show certified/uncertified.
- **G7 — Reindex authority.** E8 reindex must exactly match how `run.py` builds `prospector.db`;
  reuse that code path, don't reimplement.

---

## 8. Phasing (suggested)

- **Phase 1 — Read-only console (signalengine parity).** Overview + Catalogue + Reports/Economics
  + Diagnostics (read), all over the existing artifacts. Zero risk, immediate value (kills the
  `cat JSON` / `report` CLI loop). Requires only G1.
- **Phase 2 — Actuate.** Run Launcher + Resume/Queue + the subprocess runner (G2, G3). The "tweak
  → rerun → watch" loop.
- **Phase 3 — Parameters with the golden veto.** The config editor + schema + certification
  (G4, G6). Highest risk, gated last, behind the truth-loop firewall.

Each phase ships behind the existing test/golden discipline; the console adds no path that can
publish or mutate verdicts outside the engine's own gates.

---

*This document is design/spec only. No code in this change. Implementation should proceed
phase-by-phase, each phase reviewed under the founder fence (money/publish paths) and gated by the
golden-set regression suite.*
