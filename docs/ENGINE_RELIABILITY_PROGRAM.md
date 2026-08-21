# Engine Reliability Programme

> Tracked programme. Append results HERE, never in `CLAUDE.md`. Sibling programmes:
> `docs/COST_PROGRAM.md` (cost levers), `docs/GRAPHIFY_ENFORCEMENT_SPEC.md` (graph freshness).
>
> **Every number in this file cites a retrievable source or is marked `HYPOTHESIS:` /
> `AGENT-REPORTED (unverified)`.** Claims sourced to a subagent are labelled as such: a subagent's
> output is a claim, not evidence, and none of them have been re-verified on disk by the author of
> this document except where noted.

Opened 2026-08-06. Scope: engine optimisation, production reliability, token/limit outage
tolerance, and off-machine monitoring via the Hermes Telegram agent.

---

## Scoreboard

| Metric | Baseline (2026-08-06) | Target | Probe |
|---|---|---|---|
| Verdict calls that bought no ruling — **CURRENT** | **45.9%** (2026-08, n=1998) | < 35% | `scripts/engine_yield.py` (to write, P1) <!-- doc-lint-ok: a deliverable of this programme; writing the file is the task, so it is absent by definition --> |
| Verdict calls that bought no ruling — all-time | 66.8% (4957/7421) — *historic average, see §3* | n/a | same |
| Live PASSes failing today's gate | ~~5 of 83~~ → **0 of 78** (all 5 re-vetted to KILL) | 0 | `scripts/replay_pass_gate.py` (to write, P0) <!-- doc-lint-ok: a deliverable of this programme; writing the file is the task, so it is absent by definition --> |
| Killed packs still publicly listed | **5** (no retract path exists — §7) | 0 | `ls store/listings/` vs `*.kill.json` |
| Live PASSes past re-vet SLA | **29 of 83**, max 21d overdue | < 5 | decay sweep counters in tick log |
| Unwired rails (impl + tested + 0 prod callers) | **6 known** (1 fixed, 5 open) | 0 | `scripts/unwired_rails.py` (to write, P2) <!-- doc-lint-ok: a deliverable of this programme; writing the file is the task, so it is absent by definition --> |
| Off-machine alert delivery | **inert** (`ALERT_WEBHOOK_URL` unset) | Telegram, debounced | `estate_alert.py --dry-run` + tick log |
| Distinguishable limit classes | **1** (everything → 3600s) | 3 (5-hour / weekly / permanent) | `tests/unit/test_errors_limits.py` (to write, P1) |

---

## 1. Root cause of the under-vetted live packs — FIXED (uncommitted)

**Symptom reported:** three live sellable packs carry `decision: pass` with only 2 of 6 checks
`supported`; `58639bfc8b92de1c` is on sale having never had a legality check succeed
(conf=0.0, 1 source).

**Not the cause:** the PASS threshold. `min_supported_to_pass: 2` exists per lane
(`config.yaml:289-291, 332-334`) and those packs sit exactly *at* the floor, not under it. Lowering
or raising a threshold was never the repair.

**The actual cause:** `prospector/decay.py::run_decay_loop` — the SLA re-verification rail — **had no
production caller.** Its only importer was `tests/sim/test_decay.py`. So `reverify_due_at` was a
write-only field in production: gates tightened, and already-published dossiers were never re-judged.

**Evidence:**

| Fact | Source |
|---|---|
| 5 of 83 live PASSes fail today's gate | replay of `dossier.py:78-135` logic over `store/dossiers/*.pass.json` |
| all 5 minted on or before 2026-06-28 | `moat_ungrounded` landed that day, commit `73ae976` |
| **zero** minted after that date fail | same replay |
| 29 of 83 past re-vet SLA, max 21 days overdue | `reverify_due_at` vs now |

The 5: `54f775d91cbe09d8`, `58639bfc8b92de1c`, `8c769d87f78016e3`, `e3416a71ddc4dfe1`,
`1990c975d0a46ea8`. Note `58639bfc8b92de1c` is `side_hustle`, whose moat check is `buyer_intent`
— a check its dossier does not even contain, because it predates the lane-aware gate.

> **Instrument-failure disclosure.** The first replay returned 83/83 failing, including dossiers
> minted today by current code. That was my script, not the engine: check objects key on
> `check_name`, not `name`, so `moat_grounded` was always 0. Corrected figure is 5 of 83. Recorded
> here because the wrong number was nearly reported as an engine finding.

### The defect that made wiring it dangerous

`run_decay_loop` called `vet_candidate(..., store=store)` and treated every non-PASS as a delisting.
`Store.save` writes `{cid}.{decision}.json` **and deletes the stale-decision file**
(`store.py:178-182`). A re-vet that DEFERRED — the ruling returned when the moat is down, i.e.
precisely "we could not look" — would have written `{cid}.defer.json`, deleted `{cid}.pass.json`,
and re-pointed the index. **One provider outage would have permanently delisted live sellable packs
and destroyed their dossiers.**

Fix: the re-vet runs with `store=None`, and only a DECISIVE outcome
(`_DECISIVE = {PASS, KILL}`, `decay.py:50`) is persisted. A DEFER leaves the PASS untouched and is
retried. `ProviderExhaustedError` breaks the sweep rather than burning budget on rows that would all
DEFER for the same reason.

### Wiring

- `prospector/run.py::run_decay_sweep(cfg, *, limit)` — mirrors `resume_deferred`'s brain
  construction so the daemon needn't import CLI argparse plumbing. Reports `metered_usd`
  (billed money only), not `cost_usd`.
- `prospector/scheduler/run_scheduled.py::_decay_pass` — called from **both** tick branches
  (normal generation, and the drain-only/suppressed branch inside its existing deadline guard).
  Failure is caught and logged; **the tick continues**, because a maintenance sweep must never take
  down generation.
- `schedule.decay_per_tick`, default **2** — deliberately not 0. Shipping the rail switched off
  reproduces the exact bug it fixes. ← **OPEN DECISION: is 2 the cadence you want?**

**Test status:** `tests/sim/test_decay.py` + `tests/unit/test_scheduler_resume_drain.py` → 28 passed.
Full `tests/unit tests/sim` → **844 passed, 2 skipped, exit 0**, 288.31s.

**Not done:** re-vetting the 5. It needs a live moat, costs CLI slots and touches live catalogue
state. ← **OPEN DECISION.**

---

## 2. The bug class: unwired rails

`decay.py` was not a one-off. **`resume_deferred` was the identical bug six weeks earlier** — its own
docstring records it: 113 `.defer.json` dossiers sat unvetted while `alerts.py:219` told the operator
they would auto re-vet. Both cases were: fully implemented, fully tested, **zero production callers**.

A green test suite cannot detect this class, because the tests *are* the callers. That is the
defining property and it is why this needs a mechanical probe, not vigilance.

### Register

| # | Rail | Prod callers | Status |
|---|---|---|---|
| 0 | `decay.py::run_decay_loop` | 0 → **wired** | **FIXED** (verified: full suite green) |
| 1 | `control_center/runner.py:835::sweep_old_logs` | 0 | open — logs accumulate forever |
| 2 | `kill_decay.py:18::get_active_steers` | 0 | open — kill-rate steering never activates |
| 3 | `kill_decay.py:257::re_seed_suggestions` | 0 | open — suggestions never refresh |
| 4 | `kill_decay.py:120::check_diversity_floor` | 0 | open — no kill-clustering detection |
| 4a | `kill_decay.py::get_stale_domains` | 0 | open — same module, same sweep |
| 4b | `kill_decay.py::decayed_kill_ids` / `iter_revet_claims` | 0 | open — **and would return 0 rows if wired**; see below |
| 5 | `scheduler/guard.py:266::guard_check` | 0 | open — deprecated; `guard_from_config` is live |

> Rows 1 and 5 remain **AGENT-REPORTED (unverified)** — from a caller-graph sweep excluding
> `tests/` and `scripts/`. Each must be re-verified on disk before it is wired.
>
> **Rows 2–4b are VERIFIED on disk, 2026-08-20.** `rg` over the tree for all six public names in
> `kill_decay.py`, excluding the module itself and `tests/`, returns only two `specs/*.md` design
> documents and this file. The earlier hypothesis — "`kill_decay.py` is dead wholesale" — is now a
> finding: the module has no production caller at all, not three separate omissions.
>
> **Row 4b carries a second defect, and it is the one that matters if anyone wires this module.**
> `decayed_kill_ids` requires a top-level `verdict == "KILL"` and reads its date from
> `killed_at` / `timestamp` / `ts`. Real dossiers carry neither. Measured over the 2,698
> `*.kill.json` files in `store/dossiers/`: **0 have a top-level `verdict` key** (they carry
> `decision`, whose value is the lowercase string `kill` on all 2,698) and **0 have `killed_at`**
> (they carry `created_at`, on all 2,698).
>
> Two angles, and they agree. The key census above is one. Running the function against that real
> corpus is the other: `decayed_kill_ids` returns **0 ids** at `half_life=30/revisit_below=0.5`, at
> `revisit_below=1.0`, and at `half_life=365/revisit_below=1.0` — the last of which every one of
> the 2,698 kills should clear.
>
> So the R2 per-candidate claim lock (`prospector/claim_lock.py`, `tests/unit/test_claim_lock.py`)
> guards a walker that yields nothing. Its tests pass because their fixture writes
> `{candidate_id, verdict, killed_at, domain}` — a four-key shape production has never written.
> This is the same fixture defect that hid the lint-receipt bug in `tests/test_kill_decay.py`, in a
> second file.
>
> **Deliberately not fixed here.** Correcting the read keys would make 2,698 killed candidates
> eligible for re-vet the moment anything calls the walker, and a re-vet spends money on the moat.
> That is a founder decision (LAW 11), not a drive-by patch, and there is no caller today so
> nothing is currently broken by leaving it. Wire the caller and fix the keys in the same change,
> with a bound on how many re-vets a tick may start.

Same sweep reported, also unverified: **`adaptive.py` is fully wired** (all 8 functions called from
`run.py` / `diagnostics.py`), **no write-only fields remain in the Dossier model**, and **index
reconciliation is manual by design** — the daemon detects orphaned rows (`run.py:1300-1306`) but
deliberately does not fix them; only `scripts/reconcile_orphan_index.py` does.

**P2 deliverable:** `scripts/unwired_rails.py` — walks `prospector/`, builds a caller graph with  <!-- doc-lint-ok: a deliverable of this programme; writing the file is the task, so it is absent by definition -->
`tests/` and `scripts/` excluded from the caller set, fails CI on any public function with zero
production callers that is not on an explicit allowlist. This turns a class of bug that survived two
occurrences into a build failure.

---

## 3. Engine optimisation: the central inefficiency

Measured over **7,421 check-rows across 1,511 dossiers** in `store/dossiers/`.

> **66.8% of all verdict calls (4957/7421) bought no ruling.**

That is the headline. It is not a retrieval-volume problem, and this is the surprising part:
**it survives depth.** Verdict quality by number of retrieved passages is **non-monotonic**:

| Passages retrieved | % returning no ruling |
|---|---|
| 0 | 100% (short-circuited, no verdict call — `verify.py:498-511`) |
| 1 | 66.5% |
| 2–3 | **56.7%** ← best |
| 4+ | **68.2%** ← worse than 2–3 |

**More evidence made the engine rule *less* often.**

### The controls hold

Within every check type (2–3 → 4+): `payer_solvency` 68.3% → 79.7%; `legality` 61.1% → 75.1%;
`pain_reality` 53.4% → 71.5%; `value_durability` 57.1% → 61.9%. Within every month: June 75% → 97%;
July 31% → 61%; August 32% → 48%. So it is neither a check-mix artifact nor a provider-era artifact.

All **2,355** rows that retrieved 4+ passages, paid a full verdict call, and returned no ruling used
**2 queries** — the configured maximum (`config.yaml:92`, `queries_per_check: 2`). The second query
is therefore the concrete target: it is what pushes a check from the 2–3 band into the 4+ band.

**HYPOTHESIS: passage dilution.** Beyond ~3 passages the verdict prompt loses the signal in the
noise. The remaining unexcluded confound is reverse causality — obscure candidates need more queries
*and* are inherently harder to rule. **Note the confound predicts the opposite direction at the high
end**, which strengthens rather than weakens the dilution reading, but does not settle it.

**Decisive test (P1):** A/B the same candidate set at capped vs. full passage depth using the
existing `store/runs/control_experiment_*.log` harness. Kill criterion: if capped depth does not
raise the ruling rate, dilution is dead and the effort moves to prompt/query quality instead.

### Retracted

I was about to propose "skip the verdict call when retrieval returns zero sources" as a guaranteed
~6.6% saving (492 rows, all 100% unverifiable). **`verify.py:498-511` already does this**
(`short_circuit_empty=True`). Not a saving; it is already banked. Recorded so it is not re-proposed.

### Bottleneck checks, by rate of no-ruling

payer_solvency 76.4% · legality 71.9% · incumbency 70.0% · distribution 67.4% ·
pain_reality 66.6% · value_durability 64.2%

`payer_solvency` and `legality` are worst and are also, respectively, the moat-critical check for the
`smb` lane and a universal gate. Prompt work should start there.

### Outcome mix by month

| Month | n | PASS rate |
|---|---|---|
| 2026-06 | 824 | 2.1% |
| 2026-07 | 263 | 12.2% |
| 2026-08 | 424 | 8.0% |

---

## 4. Token outage, session limits, weekly limits, graceful resumption

**What works today.** `errors.py:100-190` classifies TRANSIENT backpressure (`\b(429|503|529)\b`,
`overloaded_error`) from PERMANENT exhaustion (`\b402\b`, credit balance,
`_ALLOWANCE_LIMIT_RE = \b(spend|usage|monthly|weekly|daily)\s+limit\b`); PERMANENT wins ties.
Transient → 60s dead mark, permanent → 1h (`health.py:54`). `health.py:130::_claim_probe` makes the
mark half-open so exactly one caller machine-wide re-probes, and a brain that recovers in 90s is
back in 90s.

**The gap, verified.** `parse_reset_seconds` reads only **relative** durations — `retryDelayMs`, and
`_RESET_HMS = reset(?:\s+\w+){0,3}?\s+after\s+([0-9hms\s]+)`. A grep across `prospector/` for
`5[- ]hour|five[- ]hour|weekly limit|resets? at|reset_at|session limit` returns **zero matches**.

Consequence: **Claude Code's weekly limit, which resets at an absolute time, parses to nothing.** It
falls through to `DEFAULT_EXHAUSTION_S` (3600s). The daemon then re-probes a brain that is guaranteed
dead **once an hour for up to a week** — every probe a full-price failed call, every tick logged
`moat_blind`. Nothing in the codebase distinguishes a 5-hour window from a weekly limit from a
permanent 402.

**P1 design.**

1. **Parse absolute resets.** Extend `parse_reset_seconds` to handle `resets at <ISO8601>` /
   `resets at <H:MM(am|pm)>` and clamp the derived dead-mark to the stated wall-clock time. Tests:
   `tests/unit/test_errors_limits.py` with real CLI strings as fixtures.
2. **Three limit classes, not one.** `SESSION_5H`, `WEEKLY`, `PERMANENT`, each with its own default
   when no reset time is parseable (5h / 7d / 1h-then-alert). Classification stays in the single
   shared tested function, per the existing "a dead brain must leave a trace" rule.
3. **Resumption is already correct and must stay so.** DEFER + `vet --resume` for the moat,
   `signals/pending/` + `generate --resume` for generation, and now the decay sweep's `stopped_early`
   break. The fix is *when we retry*, not *whether we recover*.
4. **Alert on class change, not on every failure.** A WEEKLY classification is the one event that
   genuinely needs the founder's attention, because nothing automatic will clear it. See §5.

---

## 5. Monitoring: no black box, off-machine, via the Hermes Telegram agent

### What Prospector has

7 alert codes — `tick_error`, `barren_generation`, `barren_streak`, `moat_deferred`,
`moat_provisional`, `zero_yield`, `liveness` — and 4 sinks: `store/scheduler/alerts.jsonl`,
`store/scheduler/ALERT.txt`, a macOS `osascript` desktop notification, and an opt-in webhook POST.
*(alert-code inventory is AGENT-REPORTED, unverified.)*

**Prospector has zero Telegram code.**

### The finding: the off-machine sink has never been armed — VERIFIED

`prospector/scheduler/alerts.py:226` reads `os.environ.get("ALERT_WEBHOOK_URL", "").strip()`.
There is **no assignment** in `.env`, `~/.zshrc`, `~/.zprofile`, or any installed LaunchAgent plist.
Every `ALERT_WEBHOOK_URL` hit in `~/Library/LaunchAgents/com.prospector.watchdog.plist` is **prose
inside a comment** telling the operator to set it. It was never set.

So today, all four sinks are machine-local. If the Mac is asleep or the founder is away, **every
alert this engine raises is invisible.** That is the black box.

### What Hermes has — VERIFIED

- `~/.hermes/scripts/estate_alert.py:63` —
  `send_operator_alert(text: str, *, debounce_key: str | None = None, debounce_s: float = 300.0, dry_run: bool = False) -> bool`.
  Gateway-independent. **Returns False, never raises**, on missing creds, debounce, or network error
  — "alerting must never crash the caller" is its documented contract, which matches the rail
  discipline this engine already applies elsewhere.
- Credentials are **live**: `TELEGRAM_BOT_TOKEN` (len 46) and `TELEGRAM_HOME_CHANNEL` (len 10), both
  non-empty in `~/.hermes/.env`. Verified without printing values.
- Debounce state: `~/.hermes/logs/.alert-debounce.json`.
- Hermes already registers Prospector daemon commands at
  `~/.hermes/hermes-agent/gateway/operator_shell/prospector_daemon.py` *(AGENT-REPORTED)*.

### Recommendation: import the function, do not set the webhook

Setting `ALERT_WEBHOOK_URL` to Telegram's API cannot work as-is — Telegram needs a specific
`chat_id`/`text` payload, which a generic Slack/Discord-shaped POST will not produce. `estate_alert`
already builds exactly that payload, plus debounce, plus the never-raises contract.

**P0 seam:** add a fifth sink to `alerts.py` that calls `send_operator_alert` via a guarded import
of `~/.hermes/scripts/estate_alert.py`, with `debounce_key=<alert_code>`. Requirements:

- Wrapped so a missing or moved Hermes checkout degrades to the existing 4 sinks, never an exception.
- No new credentials in this repo, no hosted service — the token stays in `~/.hermes/.env`. This
  keeps the "no hosted service / no API-key calls beyond this repo" rule intact: the call is a local
  import of a local script that the founder already owns and already runs.
- Tests must **never** send. Memory records `test_coordinator.py` messaging the founder for real;
  the test seam is `dry_run=True` and a monkeypatched sender, and that fence is the acceptance
  criterion for the change, not an afterthought.

### Escalation policy (which of the 7 codes actually reach Telegram)

| Code | Telegram? | Why |
|---|---|---|
| `liveness`, `tick_error` | yes | the daemon is down or crashing; nothing self-heals |
| new: `limit_weekly` (§4) | yes | nothing automatic clears it; only the founder can |
| `zero_yield`, `barren_streak` | yes, debounced 6h | sustained economic failure |
| `moat_deferred`, `moat_provisional` | local only | self-healing by design; DEFER is not an error |
| `barren_generation` | local only | single-tick noise |

The principle: **Telegram is for states that will not clear without a human.** A rail that pages on
self-healing conditions gets muted, and a muted rail is an unwired rail with extra steps.

### Closing the estate loop

`~/.hermes/scripts/verify_estate.sh` is read-only (exit 0 = OPERATIONAL, 1 = DEGRADED) and its ALERTS
section fails when `~/.hermes/state/delivery_proof.json` is older than 15 days. **Prospector does not
write that file.** *(AGENT-REPORTED.)* Having the decay sweep or a successful publish stamp it makes
Prospector's health visible to the estate probe the founder already trusts — and satisfies "state is
a probe, not a paragraph" for this engine.

---

## 6. Plan

**P0 — stop the bleeding (this week).**
1. Commit the decay fix (§1). Uncommitted on `fix/durable-ledger-fence`, suite green.
2. Confirm `schedule.decay_per_tick: 2`. ← decision
3. Re-vet the 5 pre-gate PASSes. ← decision
4. Wire the Telegram sink (§5) with the dry-run test fence.
5. `scripts/replay_pass_gate.py` — make "live PASSes failing today's gate" a probe, not a memory.  <!-- doc-lint-ok: a deliverable of this programme; writing the file is the task, so it is absent by definition -->

**P1 — reliability and yield (next).**
6. Three limit classes + absolute reset parsing (§4).
7. The passage-dilution A/B (§3). Settle it, then either cap depth or move to prompt work.
8. Prompt work on `payer_solvency` and `legality` — the two worst checks.

**P2 — make the class extinct.**
9. `scripts/unwired_rails.py` in CI (§2).  <!-- doc-lint-ok: a deliverable of this programme; writing the file is the task, so it is absent by definition -->
10. Verify rails 1–5 on disk, then wire or delete each. Deleting is a legitimate outcome; a rail
    nobody wants is cheaper gone than dormant.
11. Stamp `delivery_proof.json` so the estate probe sees this engine.

---

## 7. Progress log — 2026-08-06 (second session)

### The inefficiency is HISTORIC, not current — correction to §3

§3's headline 66.8% is an all-time average dominated by June, which is 56% of all rows:

| Month | rows | no-ruling |
|---|---|---|
| 2026-06 | 4180 | **81.7%** |
| 2026-07 | 1243 | 50.0% |
| 2026-08 | 1998 | **45.9%** |

**The correction that matters more:** §3 argued the depth effect was non-monotonic (2–3 sources
beating 1) and that this pointed *away* from the obscurity confound. In the last 30 days the
inversion is gone and the gradient is cleanly monotonic — 1 source 13.0%, 2–3 31.5%, 4+ **53.6%** —
which is exactly what pure reverse causality predicts. **The passage-dilution hypothesis is now
LESS supported than §3 states, not more.** No depth cap should ship until the A/B settles it. What
is still true and still worth acting on: 4+ is 2152 of 3049 non-zero rows, so whatever is happening
governs 71% of current volume.

### Re-vetting the 5 — all five were dead

Run 2026-08-06 with decay's DEFER-safe semantics (`store=None`, decisive-only persistence):

| Candidate | Gate fired | supported |
|---|---|---|
| `54f775d91cbe09d8` | incumbency | 0 |
| `58639bfc8b92de1c` | payer_solvency | 0 |
| `8c769d87f78016e3` | value_durability | 0 |
| `e3416a71ddc4dfe1` | incumbency | 0 |
| `1990c975d0a46ea8` | value_durability | 0 |

**5 of 5 KILL, every one on a grounded REFUTATION rather than an unverifiable** — these were not
retrieval failures, they were dead ideas that had been on sale since June. Catalogue moved 83 → 78
live PASSes. This retires the "is the decay rail worth its cost" question: one sweep found a 6%
false-positive rate in the live catalogue.

### THE THIRD OCCURRENCE OF THE BUG CLASS — no retract path

The re-vet exposed a new instance of the same class, and it is the most serious one:

- `store/listings/*.json` for all 5 killed packs **still exist**.
- `api.py:89-109` serves `/v1/listings` by globbing that directory.
- `bridge.py:663` sets `isListed` **only at publish time**; nothing anywhere sets it false.
- Grep for `def .*unlist|def .*retract|def .*delist` across `prospector/` → **no matches**.

So a KILL changes the dossier store and nothing else. The catalogue can now retire a pack; the
storefront never hears about it. Before this session that was latent (nothing ever produced a
post-publish KILL). The decay rail makes it live, and the re-vet has already created the drift:
**5 packs are KILL locally and still advertised.**

Deliberately NOT fixed unilaterally. Retracting a listing is outward-facing, and if any of the five
has already sold it has customer implications. It also touches `bridge.py`, which is the money rail
— founder-fenced. ← **OPEN DECISION.**

### Shipped this session

**Token limits (§4) — implemented and wired.**
- `errors.py`: `LIMIT_SESSION_5H` / `LIMIT_WEEKLY` / `LIMIT_NONE`, `classify_limit`,
  `_parse_absolute_reset` (ISO and bare wall-clock, "resets at 5pm" → next occurrence),
  `limit_window_seconds` (stated reset always beats a class default), `_MAX_WINDOW_S` = 7d clamp.
  `parse_reset_seconds` gained an optional `now` for a pinnable clock.
- **A second, worse bug found while testing it:** `classify_exhaustion("5-hour limit reached")`
  returned `""` — NOT_EXHAUSTION. That is the dangerous half `errors.py:98-100` already warns
  about: it never becomes a `ProviderExhaustedError`, so `verify.py` takes its generic-exception
  path and the outage is recorded as an `unverifiable` check instead of deferring the candidate.
  `_ALLOWANCE_LIMIT_RE` now covers `hourly|session` and `\d+-hour limit`.
- Wired at **both** real call sites — `operator.py::FallbackOperator._raw` and
  `retrieval.py::FallbackSearchProvider.search` — so it is not another unwired rail.
- `health.py:44`'s `_MAX_DEAD_S = 24h` clamp is deliberately LEFT ALONE: it is the rail against a
  mis-parse benching a brain forever. A weekly limit therefore re-probes daily rather than hourly
  — a 24x cut, with the safety rail intact. The 7d class default expresses intent; the clamp wins.
- Tests: `tests/unit/test_errors_limits.py`, 25 assertions on a pinned clock.

**Monitoring (§5) — implemented.**
- `alerts.py`: fifth sink `_telegram_push`, via a guarded file-load of
  `~/.hermes/scripts/estate_alert.py`. `TELEGRAM_KEYS = {liveness, tick_error, zero_yield,
  barren_streak}` — self-healing conditions stay local.
- **Test fence hardened after it failed once in practice.** `dry_run=True` was not enough:
  `tests/scheduler/test_run_scheduled.py` reached the real sender, and Hermes checks `_debounced()`
  *before* `dry_run`, so a test run writes `~/.hermes/logs/.alert-debounce.json` and could suppress
  a genuine founder alert for 30 minutes. `_load_hermes_sender` now returns None outright when
  `PYTEST_CURRENT_TEST` is set — the module is never loaded under pytest.
- Tests: `tests/scheduler/test_telegram_sink.py`.

**Anti-regression for the bug class:** `tests/scheduler/test_tick_decay.py` asserts the *wiring* —
that a tick calls the sweep, that the default is not 0, and that a failing sweep cannot take down
generation. A green suite could not previously see an unwired rail, because the tests were the
callers.

**Suite:** 225 passed on `tests/scheduler tests/unit/test_errors_limits.py tests/sim/test_decay.py`.
Full `tests/unit tests/sim tests/scheduler` was 1061 passed / 1 failed / 2 skipped before the
scheduler-test fix; the one failure was this session's own decay wiring meeting a `SimpleNamespace`
fake config, now fixed. **A full-suite re-run is still owed.**

---

## 8. Progress log — 2026-08-20/21: the ops console outage, and why generation is paused

**Read this first if you find `store/scheduler/PAUSE_GENERATION` armed on the engine.** It was
armed by hand at 22:53 UTC on 2026-08-20 and the reason is written inside the file. From this
release it can also arm itself; see "The autopause" below.

### What the founder saw

"dashboard is not loading any data again". Measured inside the container, 34 console reads: **20
hit the 30s ceiling and the fastest was 8475ms.** Loadavg 25.83. CPU steal 90.7%, user 6.8%.
After the pause: nine consecutive reads at 478, 615, 620, 812, 874, 895, 1230, 1257, 1298ms,
loadavg 4.09, no 502s.

### The chain, end to end

1. The MiniMax token plan ran out. Every call came back HTTP 429.
2. `errors.classify_exhaustion` grades a bare 429 as TRANSIENT backpressure, which is correct on
   its own terms — a 429 usually means slow down, not stop.
3. So the MiniMax adapter's own ladder (`operator.py:833-861`) retried: 5s, 10s, 20s, 40s, four
   times per call. No brain was ever marked dead.
4. `_moat_blind_reason` needs EVERY verdict brain dead before it skips a tick. One brain was
   nominally alive, so it never fired and generation kept running.
5. Generation produced zero candidates, wave after wave, and the fallthrough spawned `claude -p`
   runtimes to do the query-writing. Four of them at once.
6. Four Node runtimes on a `shared-cpu-2x` took the box to 90.7% steal. The ops console
   (`next-server`, same container) was starved: `console_api` import measured 6078ms under load
   against 125ms idle.

**The engine was minting work that no brain could finish, and paying for the privilege with the
CPU the console needed to say so.**

### Why the fix is not "teach the error classifier about this 429"

`prospector/errors.py` carries four comment blocks recording the same fix attempted four times,
each time by adding the vendor's newest noun: "free usage" (2026-08-09), "free trial"
(2026-08-13), "spend limit" against "usage limit", and word boundaries on the HTTP codes. Every
one of them was correct and none of them held, because the wording is the vendor's to change.

**Grade the OUTCOME instead.** Barren generation is barren generation whichever provider is down
and whatever it says. That is the rail below.

### The autopause — new, and ON by default

`_autopause_generation_on_barren_streak` in `prospector/scheduler/run_scheduled.py`, called from
`_emit_tick_alerts` on every tick.

- The alert `barren_streak` has existed for months and stopped nothing. It now STOPS first and
  tells second.
- **One threshold, not two.** It reads the alert spec the alerter already produced, so "this is
  an outage" and "this stops generation" cannot drift apart. Change it in
  `alerts.alerts_for_tick`, once. Today: three consecutive barren real ticks.
- **Scope is `generation`, never `all`.** It arms `PAUSE_GENERATION`. The drain keeps running and
  keeps finishing the work already in the queue, which is exactly the half-stop CLAUDE.md
  describes. `PAUSE` is the liability rail and this never touches it.
- **It does not self-clear.** The founder asked for that directly: "and we can restat fron
  adnindashboard hwen we are able to". A rail that re-opens by itself re-opens into the same
  outage.
- **It writes down why.** The pause file carries the tick count, what it means, and the way back.
  `pause.arm` keeps the FIRST armer's reason, so an automatic pause never overwrites an
  operator's.
- **A stop that fails to arm is louder than one that works.** If `pause.arm` raises, the function
  emits a CRITICAL `autopause_failed` alert naming the exception and saying generation is STILL
  RUNNING, then returns without taking the daemon down with it.
- Switch: `schedule.autopause_on_barren_streak` in `config.yaml`, default `true`.

### How to resume

**From the admin console, which is what it is for.** `/engine`, the generation row, the button
reading "Start it again" (`store_platform/src/Ops.Console/src/pages/engine.tsx:823`, registered
at `prospector/ops/console_api.py:2549`). By hand:
`rm /data/store/scheduler/PAUSE_GENERATION` on the engine.

**Resume only after the provider is funded.** Nothing about this pause fixes the token plan; it
stops the engine burning CPU and subscription allowance on work it cannot finish.

### One Claude CLI process, not four

Founder directive 2026-08-20, verbatim: "for the last tine i donnt want 4 claude processes, its
epensive", "1 cludclaude cli", "not 4", "this needs to be enforce ruthlessly".

`claude_cli.MAX_CLAUDE_CLI = 1` clamps every path into the governor — `config.yaml`, the
dashboard overlay, and `PROSPECTOR_CLAUDE_CONCURRENCY` alike — and logs a warning naming the
directive when a larger number is asked for. The env var still works as a way DOWN, never back
up. `config.yaml retrieval.claude_concurrency` and `config.Retrieval.claude_concurrency` are both
1, but they are defaults; the clamp is the refusal, because a default can be overridden from the
dashboard and a clamp cannot. `tests/unit/test_one_claude_cli_process.py` fails if the ceiling
moves.

Money, not just CPU: every `claude -p` spends the subscription allowance, so four of them reach
the usage wall four times sooner.

### A pause reason written by a human now reaches the panel

Every runbook in this repo says `touch store/scheduler/PAUSE`, and an operator in an incident
writes a sentence, not JSON. `readmodel.pause_view` used to call `json.loads` on the body and
reset it to `{}` when that raised, so the console rendered `reason: null`. **A pause that renders
without a reason reads to the next person exactly like a crash.** JSON still wins when it parses;
a plain sentence now becomes the reason with `actor: hand`.

## 9. The pipeline gap — production could run code main had already taken back

Founder, 2026-08-21, on being shown that the fix for the console outage only changed production
once it was deployed: **"why, this is a gap is our pipeline process"**, and then **"we need to
iron it out properly"**.

### What was measured, three angles, all on 2026-08-21

1. **The deploy does not wait for CI.** `.github/workflows/deploy-engine.yml` fires on `push` to
   `main`. Its only gate is `deploy: needs: test`, and that `test` job is the Ops.Console lane —
   `npx tsc --noEmit` and `npx vitest run`. Nothing else is graded before the image ships. The
   probe printed the proof during this very session: production on `61cfb7d1` while
   `scripts/live_checkout.py` reported `CI on it   pending: still in_progress` for that same
   commit.
2. **One of the two main guards reverts without re-deploying.** `main-admission-guard.yml` does
   the right thing: its step "Put the estate back, not just git" dispatches every deploy the bad
   commit had already set off. `main-green-guard.yml` does not. It pushes the revert with
   `GITHUB_TOKEN`, which starts no workflow runs — deliberately, so it cannot recurse — and then
   dispatches CI and only CI. Its own header says it plainly: *"WHAT IT DOES TO PRODUCTION.
   Nothing directly."* Eight reverts landed on main in the three days to 2026-08-21.
3. **Nothing compared the running image to main.** Before this work, `rg deployed_commit` and
   `rg GIT_SHA` matched exactly one file in the repo — `scripts/live_checkout.py` — which runs
   when a person runs it. None of the fifteen workflows checked for drift.
   `com.prospector.live-update`, the launchd job that would have run the probe every 60 seconds,
   is not loaded.

Put together: a red commit can reach production, be reverted on main, and **keep serving**, with
every instrument in the estate reading green. A deploy that never happens leaves no failed run
behind, so no alert here could ever have fired on it.

### What was built

`scripts/deploy_reconcile.py` plus `.github/workflows/production-runs-main.yml`. It asks the one
question that stays true whatever the cause: **is the image production is running the one main
says it should be?** When it is not, and the difference is real, it dispatches
`deploy-engine.yml`. It never builds and never pushes, so there is still exactly one route to
production with its gates and its rollback intact.

It reuses rather than reimplements. `live_checkout.deployed_commit()` reads `/app/GIT_SHA`,
`live_checkout.ci_verdict()` grades main, and `live_checkout._deployed_changes()` reads the
shipped-paths filter out of `deploy-engine.yml` on origin/main — a second copy of that filter
would drift silently in the one direction that matters, production graded current while a real
change sits unshipped, and `test_the_deploy_path_filter_is_never_copied_into_this_script` fails
if anyone copies it.

**The eight refusals, which are most of the value:**

| situation | what it does | why |
|---|---|---|
| main's CI is `fail`, `none` or `unknown` | refuses, opens the issue | shipping an ungraded commit to close a drift is worse than the drift |
| the image stamp cannot be read | refuses, opens the issue | "I could not tell" is never "it is fine", and never a licence to deploy |
| a deploy is already running | waits | the same reason `deploy-engine.yml` sets `cancel-in-progress: false` |
| 3 deploys already dispatched in 6h | refuses, opens the issue | every release up to v15 shipped without `GIT_SHA`; a drift that cannot close would otherwise pay for a Fly build every hour, forever |
| a secret is staged on the app | refuses, names the secret | **a Fly deploy APPLIES staged secrets.** Without this the robot turns "a session staged a credential" into "it is live in production", hourly, with nobody in the path at the moment it happens. Not hypothetical: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_HOME_CHANNEL` were staged on this app on 2026-08-20 precisely so they would not go live until someone chose |
| the secret list cannot be read | refuses | flyctl and the token are both in the step's env, so a failure there is a fault rather than an absence |
| `~/.prospector/ACTIVE` says a side that is not `fly` | refuses | `AUTOFAILOVER` is armed, so the serving side can move with no human. Deploying the side that is not serving restarts four processes on a box nobody is using |
| `~/.prospector/ACTIVE` is absent | **proceeds, and says so** | the opposite direction from every other row, deliberately. That marker lives in a home directory on the laptop and can never exist on a GitHub runner, so refusing on absence would make the robot permanently inert in the only place it actually runs |

It also does nothing when the commits differ but nothing the image ships does. A docs merge is
not a drift, and an alarm that is usually wrong is one that gets ignored.

**Triggers and cost.** Hourly cron, plus one run every time CI concludes on main — which is the
moment a drift can first be healed, and exactly the case a `main-green-guard` revert leaves
behind. About 24 runs a day, each a checkout, a flyctl setup and one `fly ssh` read.

**Alerting.** A failure opens a GitHub issue titled `production is not running main`, reuses that
issue rather than duplicating it while the drift lasts, and closes it on the first run that finds
production on main. The alarm step hangs off `failure()` of the check itself and nothing
narrower, because a reporting mechanism whose trigger is narrower than the thing it reports on is
never reached while every instrument still reads green
(`tests/unit/test_an_alarm_must_run_when_the_thing_it_alarms_on_fails.py`).

### The last four rows of that table are LAW 11 paying for itself

The first three refusals were mine. The last four came back from a peer review of the plan,
before it landed, and neither of the two risks behind them was visible from inside this
session: that a Fly deploy applies staged secrets, and that `~/.prospector/ACTIVE` can move
the serving side with no human. The correction to the correction was mine — the peer asked
for a refusal when `ACTIVE` is not `fly`, which would have made the robot inert on
`ubuntu-latest`, where that file cannot exist at all.

One more thing the estate refused, and was right to: the workflow was first called
`deploy-reconcile.yml`. `tests/unit/test_every_deploy_ships_on_green_main.py:86` globs
`deploy-*.yml` and holds every match to the contract of a workflow that SHIPS code — on a
push to main, in the admission guard's re-dispatch map, with matching path filters. This one
dispatches a deploy and never ships anything, so it is `production-runs-main.yml` now.

### What this does NOT fix, and why it was not taken unilaterally

Hole 1 stays open. The reconciler heals a bad state; it does not prevent one. Making
`deploy-engine.yml` wait for CI green — a `workflow_run` gate instead of `on: push` — would stop
an ungraded commit reaching production at all, but it also changes the deploy latency for every
merge and puts the deploy behind a ~25 minute CI run, which is the kind of change that needs the
founder's ruling rather than an agent's. It is the next decision on this file, not a task.

## Open decisions (not taken unilaterally)

1. **Re-vet the 5 pre-gate PASSes now?** Needs a live moat, costs CLI slots, touches live catalogue
   state. Under the fixed loop a DEFER cannot delist them, so the downside is bounded to spend.
2. **Is `schedule.decay_per_tick: 2` the right cadence?** At 2/tick on a 2h tick, the 29 overdue
   clear in roughly 29 hours.
