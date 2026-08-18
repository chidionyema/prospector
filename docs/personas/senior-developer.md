# Senior Developer

**What this is.** A working map of the code for the engineer who has to change it without
breaking it: where everything lives, what the contracts are, how a run and a tick actually
execute, the bug classes this codebase keeps producing, and the test that catches each mistake.
**Read this if** you are about to edit `prospector/`, `store_platform/src/`, or anything the
scheduler calls.
**Measured 2026-08-18.** Every count, path and line number below came from a command I ran this
session. Unproven statements are labelled `HYPOTHESIS:` with the check that would settle them.

Siblings: [`architect.md`](architect.md) (how the deployed units hang together — read it for the
Fly apps, volumes, seams and blast radii), [`principal-developer.md`](principal-developer.md),
[`qa-test-engineer.md`](qa-test-engineer.md), [`sre-on-call.md`](sre-on-call.md),
[`data-engineer.md`](data-engineer.md), [`README.md`](README.md). Estate spine:
[`../ESTATE_MAP.md`](../ESTATE_MAP.md).

---

## 0. Re-measure this document

```bash
ls prospector/*.py | wc -l                                    # 101
find prospector -name '*.py' -not -path '*__pycache__*' | wc -l   # 135
find prospector -name '*.py' -not -path '*__pycache__*' | xargs wc -l | tail -1   # 64,836
find tests -name 'test_*.py' | wc -l                          # 383
rg -c '^\s*def test_' tests | awk -F: '{s+=$2} END {print s}'  # 4,361
wc -l config.yaml prospector/run.py prospector/models.py       # 2602 / 4470 / 573
.venv/bin/python scripts/popdd_verify.py --staged             # the gate, without committing
```

---

## 1. Where does X live

### 1.1 `prospector/` — 101 top-level modules, 135 files, 64,836 lines

Grouped by job. Every name below is a real file; `ls prospector/*.py` prints the same list.

**The spine (read these first, in this order).**

| Module | Lines | Job |
|---|---|---|
| `models.py` | 573 | Every data contract. §2 tabulates it. |
| `config.py` | 1,224 | Loads `config.yaml`, owns `store_root()`. |
| `run.py` | 4,470 | CLI entry point, RUN.md's eight steps. §3. |
| `operator.py` | 1,791 | The swappable brain. `moat_primary()`, `is_provisional_provider`. |
| `verify.py` | 1,269 | The moat: query gen → fetch → verdict, kill-fast. |
| `retrieval.py` | 2,511 | Grounding chain, cache, per-provider breakers. |
| `scheduler/run_scheduled.py` | 2,916 | The daemon tick. §4. |
| `ops/console_api.py` | 2,862 | The ops console's only entry point. |
| `bridge.py` | 2,477 | The money rail: Price + catalogue row, together. |
| `errors.py` | 431 | `classify_exhaustion`, `looks_exhausted`. |
| `health.py` | 348 | Dead marks, half-open probes, `moat_blind_reason`. |
| `paths.py` | 74 | The *other* store-root resolver. §5.2. |

**Pipeline stages.** `generate.py`, `dedup.py`, `prescreen.py`, `prescreen_prefilter.py`
(embedding-based, wired off in `config.yaml`), `kill_filter.py`, `score.py`, `dossier.py`,
`store.py`, `price_comparables.py`, `pricing.py`, `price_rationale.py`, `critique.py`,
`adversarial` logic inside `verify.py`.

**Pack rendering — 17 modules, all deterministic and model-free by rule.** `pack_bear_case.py`,
`pack_card.py`, `pack_checklist.py`, `pack_data.py`, `pack_field.py`, `pack_floors.py`,
`pack_html.py`, `pack_kicker.py`, `pack_linter.py`, `pack_manifest.py`, `pack_offer.py`,
`pack_pdf.py`, `pack_reference.py`, `pack_table.py`, `pack_toolkit.py`, `pack_validation.py`,
plus `artifacts.py`. Read `docs/PACK_NARRATIVE_PROGRAM.md` before touching any of them.

**Prose and quality gates.** `copy_lint.py`, `house_style.py`, `plain_text.py`,
`prose_measure.py`, `prose_target.py`, `register_lint.py`, `figure_check.py`,
`numeric_citation.py`, `claim_lock.py`, `content_contract.py`, `shelf_copy_repair.py`.

**Brains and transports.** `claude_cli.py`, `gemini_cli.py` (present; no config selects it),
`cli_auth.py`, `cli_governor.py`, `breaker.py`, `usage_wall.py`.

**State and bookkeeping.** `audit.py`, `store.py`, `jsonl_atomic.py`, `metrics_store.py`,
`spend.py`, `telemetry.py`, `progress.py`, `drain_state.py`, `inflight.py`, `archive.py`,
`decay.py`, `kill_decay.py`, `pass_ceiling.py`, `coverage.py`.

**Catalogue shaping.** `facets.py`, `facet_derive.py`, `markets.py`, `landscape.py`,
`lane_yield.py`, `diversity.py`, `novelty.py`, `sampling.py`, `trimming.py`, `classify.py`,
`admissibility.py`, `denylist.py`, `entity_templates.py`, `attribution.py`, `evidence_budget.py`.

**Everything else.** `api.py`, `canary.py`, `consumer.py`, `discover.py`, `diagnostics.py`,
`field_write.py`, `golden.py`, `golden_gen.py`, `human_review.py`, `indexnow.py`,
`marketing_assets.py`, `prompts.py`, `report.py`, `self_modify.py`, `simulation.py`,
`adaptive.py`, `artifacts.py`.

**Subpackages.**

| Package | Files | Contents |
|---|---|---|
| `prospector/domain/` | 2 | `primitives.py` |
| `prospector/ops/` | 20 | `console_api.py`, `readers.py`, `readmodel.py`, `data.py`, `metrics.py`, `money.py`, `runs.py`, `routing.py`, `spend.py`, `shop.py`, `pause.py`, `supervisor.py`, `runner.py`, `undo.py`, `config_editor.py`, `yaml_surgery.py`, `automations_view.py`, `content_breaches.py`, `_cache.py` |
| `prospector/pipeline/` | 6 | `generator.py`, `verifier.py`, `middleware.py`, `moat_contract.py`, `moat_prompts.py` |
| `prospector/scheduler/` | 6 | `run_scheduled.py`, `guard.py`, `alerts.py`, `status.py`, `paths.py` |

There is no `prospector/publish/` package and no `prospector/publish.py`. Publication lives in the
top-level `publish/` package. There is no `prospector/control_center/` — the Streamlit console was
deleted; the console is the Next.js app under `store_platform/src/Ops.Console/`.

### 1.2 `store_platform/src/` — the .NET and Next.js side

| Directory | Stack | Job |
|---|---|---|
| `Store.Api/` | .NET 9 minimal API (`Store.Api.csproj:4` `net9.0`) | Catalogue, checkout, webhooks, fulfilment, delivery, ops endpoints |
| `Store.Catalog/` | .NET class library | `Persistence/StoreDbContext.cs` — 13 DbSets on an `IdentityDbContext` |
| `Store.Web/` | Next.js 16 pages router | mumchimp.com |
| `Ops.Console/` | Next.js | The admin console. Ships inside the engine image; see [`architect.md`](architect.md) §2.5 |
| `Store.Tests/` | xUnit | The .NET lane |

`Store.Api/Endpoints/` holds seven files: `AnalyticsEndpoints.cs`, `BackupEndpoints.cs`,
`CheckoutEndpoints.cs`, `DeliveryEndpoints.cs`, `FounderPreviewEndpoints.cs`, `OpsEndpoints.cs`,
`WebhookEndpoints.cs`. `Store.Api/Services/` holds the fulfilment and storage layer:
`FulfilmentService.cs`, `DeliverySweeper.cs`, `DeliveryDrain.cs`, `IContentStorage.cs`,
`CruxContentStorage.cs`, `LocalContentStorage.cs`, `R2StorageBridge.cs`.

### 1.3 `scripts/` — 41 entries, things you run

| Group | Files |
|---|---|
| Gates and CI | `popdd_verify.py`, `ci-gate.sh`, `ci_local.py`, `ci_capacity.py`, `test_impacted.py`, `load_gate.py`, `warm_ci_uv_cache.sh` |
| Estate probes | `estate_map.py`, `live_checkout.py`, `ops_status.py`, `ops_state.py`, `watch_engine.py`, `blocker_probe.py`, `site_spec_probe.py`, `pack_banner_probe.py` |
| Store and backup | `backup_store.py`, `restore_drill.py`, `store_audit.py`, `store_migrate.py`, `reconcile_orphan_index.py` |
| Backfills | `backfill_ladder_prices.py`, `backfill_price_anchors.py`, `backfill_tiers.py`, `backfill_packs_parallel.sh` |
| Docs and lint | `doc_lint.py`, `copy_audit.sh`, `guard_protected_deletions.py` |
| Graph | `graphify_sweep.py`, `graphify_query_hook.py`, `graphify_session_hook.py` |
| Ops plumbing | `launchd_plists.py`, `run_ops_console.sh`, `setup_worktree.sh`, `engine_failover.py`, `gen_budget_guard.py`, `handoff.py`, `prune_branches.py`, `branch_backlog.py`, `unit_economics.py`, `seed_action_cache.sh`, `verify_engine_change.sh` |
| Guards | `claude_guards/` (directory) |

### 1.4 `tools/` — 45 entries, things that change data

Backfills (`backfill_*.py` ×7 plus `backfill_missing_listings.sh`), catalogue surgery
(`retitle_catalogue.py`, `reprice_live_packs.py`, `reprice_to_charm_rungs.py`,
`set_live_pack_price.py`, `depth_reprice_preview.py`, `unlist_killed.py`,
`retire_rotted_passes.py`, `recover_stranded_passes.py`, `sweep_shelf_copy.py`,
`site_wide_dash_cleanup.py`), measurement (`l8_grade.py`, `l8_summary.py`, `l8_ab.sh`,
`generation_survival.py`, `prove_diversity.py`, `prove_reliability.py`, `pack_defect_census.py`,
`meta_shape_monitor.py`, `citation_quality_by_provider.py`, `floor_signature.py`,
`spend_today.py`, `price_history.py`), publication (`publish_passes.py`, `publish_offline.py`,
`preview_packs.py`, `verify_pass_shelf_coverage.py`, `verify_selling_catalogue.py`), and the
swallow auditor (`audit_swallow_sites.py`).

**Convention that is actually enforced:** anything in `tools/` that writes takes `--fix` as a
second explicit run and is read-only by default. `_backfill_driver.py` is the shared harness.

### 1.5 `tests/` — 383 files, 4,361 test functions

| Directory | Files | What it pins |
|---|---|---|
| `tests/unit/` | 304 | Everything narrow |
| `tests/scheduler/` | 25 | Tick gates, drain, supervision |
| `tests/ops/` | 11 | Console readers and actions |
| `tests/invariants/` | 7 | `test_two_loops_never_merge.py`, `test_audit_isolation.py`, `test_audit_attribution.py`, `test_chain_degradation.py`, `test_house_voice.py`, `test_market_prompts.py`, `test_search_observability.py` |
| `tests/behavioural/` | 6 | `test_source_or_die.py`, `test_publish.py`, `test_artifacts.py`, `test_gen_quality_e2e.py`, `test_observability.py`, `test_prescreen_preserves_novelty.py` |
| `tests/faults/` | 3 | `test_graceful_degradation.py`, `test_grounding_contention.py`, `test_synthetic_exhaustion_harness.py` |
| `tests/integration/` | 3 | `test_api.py`, `test_golden_promotion_cli.py`, `test_market_cli.py` |
| `tests/sim/` | 1 | |
| top level | 17 | `test_golden_set.py`, `test_suite_is_machine_independent.py`, `test_engine_bridge.py`, `test_pricing.py`, and others |

---

## 2. The core contracts — `prospector/models.py` (573 lines)

Read this file before writing anything that produces or consumes engine data. It is small, it is
the whole contract, and its comments carry the incidents that shaped it.

### 2.1 Enums and constants

| Name | Line | Value / members | Notes |
|---|---|---|---|
| `Verdict` | :25 | `str, Enum` | per-check outcome, including `unverifiable` |
| `Decision` | :31 | `PASS`, `KILL`, `DEFER` | the run-level outcome |
| `DEFER_GATE` | :39 | `"retrieval_unavailable"` | the gate name a DEFER records |
| `DEFER_REASONS` | :56 | frozenset: `retrieval_unavailable`, `moat_exhausted`, `vet_budget_spent`, `queued_for_vetting` | deliberately closed. Its comment cites `store/dossiers/2102bacc6dd75cf9.kill.json` — a KILL whose seven checks all read "Verdict call failed; fail-safe." |
| `CHECKS` | :68 | 11 entries: `pain_reality`, `value_durability`, `incumbency`, `payer_solvency`, `distribution`, `legality`, `buyer_intent`, `route_to_market`, `currency`, `claims_verifiable`, `price_comparables` | name → description |
| `PRICING_CHECK` | :107 | `"price_comparables"` | the one evidence-only check; it can never kill |
| `DEFAULT_CHECKS` | :111 | 6: `pain_reality`, `value_durability`, `incumbency`, `payer_solvency`, `distribution`, `legality` | the universal filter |
| `SCORE_AXES` | :114 | 6: `pain_acuity`, `money_provability`, `automatability`, … | composite = Σ(score × weight) |
| `_DENSE_REWARD_BASE` | :20 | `0.8` | |
| `_DENSE_REWARD_SPAN` | :21 | `0.2` | |
| `_DENSE_REWARD_COMPOSITE_MAX` | :22 | `5.0` | **was 6.0 until 2026-08-10.** A scale break: any stored composite from before that date is on a different scale. Do not compare across it. |

### 2.2 Dataclasses

| Class | Line | Key fields | Constructed by | Consumed by |
|---|---|---|---|---|
| `Source` | :123 | url, title, passage, source_id | `retrieval.py` | `verify.py`, `dossier.py`, pack renderers |
| `Candidate` | :170 | `title`, `one_liner`, `hypothesis`, `who_pays`, `why_now`, `tags: dict`, `automatability`, `weak_monetisation`, `candidate_id`, `structural_form`, `ambition_tier`, `market`, `refinement_history` | `generate.py`, `Candidate.from_dict` (:252) | everything downstream; `Store.save` indexes it; `EngineBridge` puts it on the catalogue row |
| `CheckResult` | :284 | `check_name`, `verdict`, `confidence`, `rationale`, `citations: list[str]`, `sources: list[Source]`, `queries`, `query_source`, `degraded: bool`, **`retrieval_failed: bool`**, `provider`, `provisional`, `untraceable_figures` | `verify.py` | `kill_filter.py`, `score.py`, `dossier.py` |
| `AdversarialResult` | :332 | | `verify.py` | `dossier.py` |
| `PriceAnchor` | :355 | | `price_comparables.py` | `pricing.py` |
| `ComparablesResult` | :377 | | `price_comparables.py` | `pricing.py`, `dossier.py` |
| `ScoreResult` | :407 | six axes + composite | `score.py` | `kill_filter.py`, catalogue |
| `Dossier` | :452 | `candidate`, `decision`, `gate_fired`, `reason`, `checks`, `adversarial`, `score`, `model_version`, `provider_chain`, `persona`, `created_at`, `reverify_due_at`, **`provisional: bool`**, `publish_status`, `publish_error` | `run.py` | `store.py`, `publish/`, the console, `tools/*` |

**Three fields carry the whole safety story.** `CheckResult.retrieval_failed` is what turns an
exception into a DEFER instead of an `unverifiable` that feeds a kill gate. `Dossier.provisional`
is what stops a non-`moat_primary` verdict from publishing. `Dossier.gate_fired` is what makes a
KILL auditable — a KILL without it is an opinion.

### 2.3 The two duck-typed helpers

`distinct_sources(checks: Any)` (:427) and `cited_claim_count(checks: Any)` (:438) both take
`Any` because two caller shapes exist in tree — a list of `CheckResult` and a list of dicts loaded
from a dossier JSON. **This is the type that promises more than the wire delivers** (§5.1). The
annotation says `Any`, which is honest; the risk is that callers assume a `CheckResult` and reach
for an attribute a dict does not have.

---

## 3. Orchestration — `prospector/run.py` (4,470 lines)

`RUN.md` names the eight steps and is the contract: GENERATE → DEDUP → PRE-SCREEN → VERIFY
(kill-fast) → GATE → secondary artifacts → publish → summary. `run.py` executes them.

### 3.1 The map

| Symbol | Line | Job |
|---|---|---|
| `_vet_workers` | :30 | concurrency for the vet fan-out |
| `enqueue_as_defer` | :215 | park a candidate the moat cannot rule now |
| `enqueue_candidates` | :257 | the queue writer |
| `_PENDING_DIR` | :427 | `signals/pending/` — failed signals for `generate --resume` |
| `_INFRA_GATES` | :521 | gates that mean "our fault", not "the idea is dead" |
| `_get_verify` | :538 | lazy import of the moat |
| `_NONCRITICAL_ORDER` | :611 | `("minimax",)` — the fallback default |
| `_NONCRITICAL_FORBIDDEN` | :614 | `frozenset({"claude_cli", "claude"})` |
| `_noncritical_order` | :987 | reads `config.yaml:136 noncritical_operator:` and strips the forbidden entries |
| `publish_and_record` | :1133 | the only path to the storefront |
| `vet_candidate` | :1219 | one candidate through the moat |
| `run_signal` | :1494 | the eight steps for one signal |
| `_cmd_vet` | :2261 | |
| `RESUME_SELECTORS` | :2392 | what `--resume` may pick up |
| `DrainSurvey` / `drain_survey` | :2465 / :2480 | what is actually drainable, and why |
| `drainable` | :2547 | **the single definition of "backlog"** |
| `_cmd_resume` | :2687 | the drain. Runs the classifier at `trusted_only=True` |
| `_cmd_consume` | :3356 | |
| `_cmd_generate` | :3396 | |
| `_cmd_generate_resume` | :3458 | |
| `main` | :4131 | argparse |

### 3.2 CLI surface

Subparsers registered from `run.py:4142`: `vet` (:4142), `signal` (:4193), `generate` (:4225),
a report parser (:4264), `consume` (:4286), `discover` (:4302), `report` (:4329), `diagnose`
(:4347), `operators` (:4355), `lanes` (:4363) with actions `list` / `nix` / `natch` / `set` /
`unset`, and `markets` (:4380) with actions `list` / `show` / `probe` / `open` / `close`.

### 3.3 Error handling — the rule that matters

**An exception is never evidence.** A verdict call that raises — quota, bad JSON, a crashed
adapter — sets `retrieval_failed=True` (`verify.py:365`), which fires the DEFER gate
(`verify.py:693`). It does not contribute an `unverifiable` check to the kill gates.

Before 2026-08-06 it did. The receipt is on disk:
`store/dossiers/2102bacc6dd75cf9.kill.json`, a KILL on `min_composite` whose seven checks all read
`unverifiable, conf 0.0, "Verdict call failed; fail-safe."` — a candidate killed by our own outage,
in a dossier that reads as fully reasoned. If you are adding a new failure path, the question to
ask is always: does the caller learn "we do not know" or does it learn "the answer is no"?

**Resume paths.** Moat exhaustion means PROVISIONAL first, DEFER only when the tail is down too
(founder directive 2026-08-08). Both populations are finalised by `vet --resume`. Failed signals
go to `_PENDING_DIR` (:427) for `generate --resume`.

**The asymmetry to preserve.** `_cmd_resume` (:2687) runs the moat classifier at the default
`trusted_only=True`; the daemon's generation preflight runs it at `trusted_only=False`. One shared
function, one parameter, so the two cannot disagree by accident. Re-vetting a `provisional` row on
a provisional brain re-stamps it `provisional` — the row does not move and the money is spent.

---

## 4. The scheduler — every gate, in order

`prospector/scheduler/run_scheduled.py`, 2,916 lines. The tick body is `:1658-1877`. Order is the
design: what sits above the drain stops everything, what sits below it stops only generation.

| # | Gate | Line | Reads | Stops |
|---|---|---|---|---|
| 1 | heartbeat | :1668 | — | nothing |
| 2 | `_refresh_tick_deadline` | :1670 | `_TICK_HARD_DEADLINE_S`; a `threading.Timer` calls `_force_exit_hung_tick` | a wedged tick |
| 3 | `guard_from_config(cfg).evaluate()` | :1671-1672 | `store/prospector.jsonl` ledger vs `config.yaml:2569 daily_cap_usd: 100.0` | everything |
| 4 | queue target | :1677 | `schedule.batch_size` (`config.yaml:2397` = 50) | — |
| 5 | **`if not decision.can_run`** | :1712 | `store/scheduler/PAUSE` | **the whole tick, generation and drain** |
| 6 | `queue_full` | :1717 | queue depth | generation |
| 7 | `dry_run` | :1727 | flag | writes |
| 8 | usage wall | :1742 | `usage_wall.reason()`, `PROSPECTOR_USAGE_WALL_MARKER` | everything |
| 9 | **moat preflight** | :1764 → def :788 | `health.moat_blind_reason(cfg, trusted_only=False)` (:819) | the whole tick, logged `moat_blind`, counted unproductive so the 5m/10m/20m retry applies |
| 10 | **generation brake** | :1789 → def :673 | `PAUSE_GENERATION` (`_GENERATION_PAUSE_FILENAME` :301), `schedule.backlog_cap` (`config.yaml:2429` = 0, off) vs `_backlog_size` (:463), `gate_generation_on_grounding` (read :660, `config.yaml:2444` = true) | **generation only** |
| 11 | drain | :1833 `_drain_pass`, :1839 `_decay_pass`, :1842 `_recover_pass` | inside `with _beating(cfg, "draining")`; budget `_DRAIN_BUDGET_FRAC = 0.15` (:837, matching `config.yaml:2433`); pacing `_drain_only_interval_s` (:933), `_drain_only_resume_per_tick` (:945) | — |
| 12 | generation | :1863 | `_noncritical_order` chain → `run.py` | — |

Supporting symbols: `producer_mode` (:266, `config.yaml:2486` = true), `code_fingerprint` (:2251),
`run_daemon` (:2311), `schedule.interval_s` (`config.yaml:2410` = 7200),
`tick_deadline_s` (:2428 = 10800), `vet_budget_frac` (:2432 = 0.85), `gen_budget_frac` (:2446 =
0.35), `lease_ttl_s` (:2457 = 7200).

**Why the rate gate replaced a stock brake.** A stock brake has unbounded memory: one outage
suppresses generation indefinitely, and a six-week-old outage was why the daemon generated nothing
one afternoon. `gate_generation_on_grounding` runs one bounded live search per tick and suppresses
generation only while retrieval is *actually* degraded, then self-clears. `backlog_cap` stays at 0
as a floor of last resort. The brake can only engage on `run.drainable()` (`run.py:2547`) — a
number the drain can move — and when that count fails it returns `None`, never `0`, so generation
stops rather than being waved through.

---

## 5. Recurring failure classes

Five classes, each with a real example in this tree and the line that proves it. These are not
hypotheticals; every one has shipped.

### 5.1 A type that promises more than the wire delivers

**Example.** `models.distinct_sources(checks: Any)` (`models.py:427`) and `cited_claim_count`
(`:438`) are annotated `Any` because they are called with both `list[CheckResult]` and
`list[dict]` loaded from dossier JSON. The annotation is honest; the danger is a caller that
assumes the dataclass.

**Worse example, same class.** `Candidate.from_dict` (`models.py:252`) has to repair its own
input: at the `tags` branch it converts a list into a dict (`tags = {str(t): True for t in
raw_tags}`) because old dossiers on disk carry `tags` as a list while the dataclass declares
`dict[str, Any]`. Two shapes, one field name, one type annotation that describes only the newer
one.

**The rule.** When a dataclass is also a wire format, the loader is part of the contract. Every
back-compat branch in `from_dict` is a shape that still exists on disk. Before you change a field
type, `rg` for it in `store/dossiers/` and find out what is actually there.

**The test.** `tests/behavioural/test_publish.py` and `tests/unit/test_listing_schema_fence.py`
pin the published shape.

### 5.2 `__file__`-derived paths that follow the code, not the data

**This is live in production right now.** The engine has two store-root resolvers:

```python
# prospector/config.py:12-31 — reads PROSPECTOR_STORE_DIR
REPO_ROOT = Path(__file__).resolve().parent.parent
def store_root() -> Path:
    override = os.environ.get("PROSPECTOR_STORE_DIR", "").strip()
    return Path(override) if override else REPO_ROOT / "store"
```

```python
# prospector/paths.py:49-69 — reads PROSPECTOR_STORE_ROOT
ANCHOR = Path(__file__).resolve().parent.parent
STORE_ROOT_ENV = "PROSPECTOR_STORE_ROOT"
def store_root() -> Path:
    override = os.environ.get(STORE_ROOT_ENV)
    return Path(override) if override else repo_root() / "store"
```

`PROSPECTOR_STORE_ROOT` is set in **no** deployment. Every deployment sets only
`PROSPECTOR_STORE_DIR` (`deploy/engine/fly.toml:30`, `deploy/engine/Dockerfile:74`,
`deploy/compose/docker-compose.yml:68`, all seven `ops/launchd/com.prospector.*.json`). Proven on
the running machine:

```
$ fly ssh console -a prospector-engine -C "/usr/local/bin/python -c \
    'from prospector import paths, config; print(paths.store_root()); print(config.store_root())'"
paths.store_root=  /app/store
config.store_root= /data/store
```

`/app/store` holds 14 files written on 2026-08-18 — seven listings and seven pricing rationales —
while the real store at `/data/store` is 555 MB with a 950,601-line ledger. Because
`prospector/ops/readers.py` resolves through `paths.store_path()` at eleven sites (`:61, :136,
:168, :212, :225, :607, :705, :743, :809, :883, :909`), **the ops console reads a different root
than the engine writes.**

**The history, which is the point.** `config.py:15`'s own docstring describes this exact defect
and records that it cost 20 minutes of split state on 2026-08-17. `deploy/engine/Dockerfile:74`
carries a comment asserting `config.store_root()` "is the only resolver". Both are the correct
lesson written next to a codebase that then reintroduced the bug in a different module.

`audit.py:55-77` documents a third instance in the same family: the audit dir default used to be
the relative string `"store/scheduler/audit"`, so the trail followed whoever launched the process.
Proven 2026-08-05 by importing the module from an empty scratch directory and watching it create
`store/scheduler/audit/<today>.jsonl` there. `~/Documents/code/sentinel-loop/store/scheduler/audit/`
still holds 10 KB of real prospector rows from 2026-06-26.

**The rule.** Never write `Path(__file__).parent.parent / "store"`. Call `config.store_root()`.
Resolve **per call**, not at import — `paths.py`'s docstring explains why anchoring to `__file__`
fixes cwd-relativity but not import-time binding: "it just makes the wrong target deterministic".

**The test.** `tests/unit/test_paths.py` — and note its design. Its docstring says a test that
only checked `store_path()` returns the right string "would not have caught that; the ones here
import a consumer FIRST and then move the root."

### 5.3 A fence installed in the wrong process

**Example.** `tests/conftest.py` had to work around `audit.py` binding `_AUDIT_DIR` at import
(`audit.py:66`), so `monkeypatch.setenv` alone was a no-op for an already-imported module. The
consequence, recorded in `paths.py:14-18`: pytest wrote fixture rows into the **production** audit
log and **1,874 fixture `LAW:` lines** into the durable ledger — junk that then fed the generator
prompt as "concepts mathematically proven to fail". The fence existed. It was installed in the
test process, after the module under test had already decided where to write.

**Second example, different axis.** `git config core.hooksPath` overrides `.git/hooks` **entirely**.
The founder disabled the pre-commit gate on 2026-08-14 by moving `.git/hooks/pre-commit` aside; on
2026-08-15 someone set `core.hooksPath` to `.git/hooks-active`, and the move silently stopped
mattering. A commit then failed with only "exit code 1" while the documentation said no gate could
have refused it. Check, never assume:

```bash
git config --get core.hooksPath              # set => THAT directory wins
ls -la "$(git rev-parse --git-path hooks)"/pre-commit
```

**The rule.** A fence is only real in the process that does the thing. Ask: which process opens the
file, spawns the subprocess, makes the network call? Install it there, and prove it with a test
that exercises the real entry point.

### 5.4 A redundant mechanism makes a test pin the wrong thing

**Example.** `tests/unit/test_popdd_gate_lanes.py` read `<root>/.git/…` as a directory. In a
worktree `.git` is a **file** containing `gitdir:`, so the test reported the POPDD gate uninstalled
in a checkout where it was installed and working. The test passed. It was measuring the wrong
object.

**The general shape.** When two mechanisms can produce the same green, a test cannot tell you which
one produced it. Ask git rather than the filesystem (`git rev-parse --git-path hooks`,
`--git-common-dir`) — that also honours `core.hooksPath`, closing §5.3's hole in the same move.

**The rule.** A guard test must fail when the thing it guards is removed. If you cannot state the
one-line change that turns it red, it is pinning something else.
`tests/unit/test_popdd_gate_cannot_wedge.py` is the counter-example done right: it pins
`single_flight` refusing a second gate run in the same tree inside a second.

### 5.5 A captured-output guard that hides a command failure

**Example, in shell.** `npm run build 2>&1 | tail` reports **tail's** exit status. A failed build
reads as `exit 0`. Capture the build's own status before any pipe.

**Example, in Python — and this is the biggest one in the engine.**
`tests/unit/test_swallowed_failures_can_only_go_down.py` exists because of it. Its docstring names
the class: "A layer catches a failure and returns something that looks like an answer:
`except Exception: return []`, `if not isinstance(data, dict): data = {}`, a fallback chain that
quietly serves the next provider. The system is built never to crash, so it never crashes — it
reports a plausible empty instead."

Measured 2026-08-15: three layers in a row destroyed one MiniMax verdict. `_extract_json` parsed
strict and a literal newline in the model's rationale raised; its Strategy 2 scanned `[`…`]` before
`{`…`}` and returned the citations array; `verdict_for` coerced that shape to `{}` below the
`except`, so nothing deferred. Out came `unverifiable, conf 0.0, rationale ""` — and the golden
promotion gate recorded that MiniMax answers without reasons. It does not. We threw its answer
away and wrote down that it was silent, in the very measurement that decides whether this engine
can run without Claude Code.

**Why a ratchet and not a ban.** Returning `[]` is often correct. The defect is never the empty
value; it is that the **caller cannot tell "nothing matched" from "it broke"**. No lint rule can
decide that. So the count may fall freely and may not rise without a human editing
`tests/unit/swallow_ratchet_baseline.json` in the same commit, where a reviewer sees it. The fix
ladder is in `tools/audit_swallow_sites.py`: propagate a typed error, or carry the failure in the
return value, before considering a waiver.

**The rule.** When you write `except Exception:`, the next line decides whether a future engineer
can debug this system. Return a value the caller can distinguish from success.

---

## 6. Code conventions actually in force

Derived from the code, not from a style guide.

1. **Config, not constants.** Anything an operator might change lives in `config.yaml` and is read
   through `config.py`. `moat_primary` was a hardcoded frozenset until 2026-08-15; making it
   `config.yaml:81` is what turned a roster change from a source edit plus a daemon re-exec into a
   config line.
2. **Resolve paths per call.** Functions, not module-level constants (`paths.py:30-31` states this
   as the module's whole purpose). Assigning `QUEUE = paths.store_path(...)` at module level
   reintroduces the bug the module exists to remove.
3. **Comments carry incidents, with dates and receipts.** `audit.py:55-77`, `config.py:15-27`,
   `models.py:39-67`, `Ops.Console/next.config.ts` are the models. A comment that says *what* the
   code does is noise; one that says *what happened when it did not* is the reason this codebase
   is debuggable.
4. **Fail loud on a stale config.** `_build_operator` raises `ValueError` for the removed
   `cursor_cli`, so a stale `config.yaml` or plist fails at startup instead of silently building a
   shorter chain.
5. **Enforce a rule where the thing is BUILT, not where it is used.** `_noncritical_order`
   (`run.py:987`) strips `claude_cli` from the non-critical chain via `_NONCRITICAL_FORBIDDEN`
   (`:614`) at construction time.
6. **Read-only first, `--fix` second.** Every sweep and backfill in `tools/`.
7. **Allow-lists over dispatch.** The console has 27 named reads and 16 named actions and cannot
   invent a 28th.
8. **A version integer on every cross-language boundary.** `console_api.py:62`
   `CONTRACT_VERSION = 1`, echoed in the envelope at `:111` and pinned on the Node side
   (`Ops.Console/src/lib/ops.ts:96`).
9. **Kill the process GROUP, drain the pipes.** `popdd_verify.py::_run_step` and
   `Ops.Console/src/lib/ops.ts:108`. Killing only the direct child leaves the real worker running.
10. **`-n auto --dist loadfile`** (`pytest.ini:42`). `loadfile` is not a performance choice: it
    keeps a file's tests on one worker because `operator._MOAT_PRIMARY` is process-global state,
    and that state is real production behaviour, not a test artefact.
11. **Plain English in comments, commits and docs.** Subject, verb, object. A commit subject says
    what changed and where.

---

## 7. Invariants, and the test that guards each

Break one and the system misleads rather than fails.

| # | Invariant | Guarded by |
|---|---|---|
| 1 | One canonical store; no `__file__`-derived store paths | `tests/unit/test_paths.py` — **but it does not cover the `config` / `paths` disagreement. That gap is why §5.2 is live.** |
| 2 | An exception DEFERS; it never contributes evidence | `tests/faults/test_graceful_degradation.py`, `tests/faults/test_synthetic_exhaustion_harness.py` |
| 3 | Swallowed-failure count may fall, never rise | `tests/unit/test_swallowed_failures_can_only_go_down.py` + `swallow_ratchet_baseline.json` |
| 4 | Only `moat_primary()` rules finally; everything else is `provisional` | `tests/invariants/test_chain_degradation.py`, `tests/test_drain_moat_preflight.py` |
| 5 | Demand never overrides truth | `tests/invariants/test_two_loops_never_merge.py` |
| 6 | Every claim cites a retrievable source | `tests/behavioural/test_source_or_die.py` |
| 7 | Pre-screen preserves novelty (nothing is killed at generation time) | `tests/behavioural/test_prescreen_preserves_novelty.py` |
| 8 | Tests never write to the production audit log or ledger | `tests/invariants/test_audit_isolation.py`, `tests/invariants/test_audit_attribution.py`, `tests/unit/test_ledger_fence.py` |
| 9 | The suite is machine-independent | `tests/test_suite_is_machine_independent.py` |
| 10 | The published listing shape does not drift | `tests/unit/test_listing_schema_fence.py`, `tests/behavioural/test_publish.py` |
| 11 | House voice and market prompts hold | `tests/invariants/test_house_voice.py`, `tests/invariants/test_market_prompts.py` |
| 12 | Search activity is observable | `tests/invariants/test_search_observability.py`, `tests/behavioural/test_observability.py` |
| 13 | The gate cannot wedge the index | `tests/unit/test_popdd_gate_cannot_wedge.py` |
| 14 | `.env` is never read where it should not be | `tests/unit/test_dotenv_fence.py` |
| 15 | The drain is supervised | `tests/scheduler/test_drain_is_supervised.py` |
| 16 | Money: the Price and the catalogue row are minted together | `prospector/bridge.py` + `tests/test_engine_bridge.py`; on the .NET side the entitlement and its outbox row commit in one `SaveChangesAsync` (`FulfilmentService.cs:94-103, :151`) |

---

## 8. How to change it safely

### 8.1 The procedure

1. **Work in a worktree.** One session, one worktree — sessions sharing this checkout share one
   `.git/index`.
   ```bash
   git worktree add --detach ../my-worktree <ref>
   ./scripts/setup_worktree.sh ../my-worktree
   ```
   The script exists because `git worktree add` produces a tree that *looks* complete and is not,
   and each gap fails by accusing something else: `node_modules` cannot be symlinked (Turbopack
   rejects any symlink leaving the project root — use `cp -Rc`); `.lux/keys/agent.pem` is
   untracked, so the hook runs and then fails for want of a signing key, reading as a gate
   violation; `.venv` is absent while the hook pins `.venv/bin/python` relative to cwd; and
   `store/` and `storage/` are tracked runtime state pytest writes to, so never `git add -A`.

2. **Check whether the gate is even installed.** It has been in both states this month.
   ```bash
   git config --get core.hooksPath
   ls -la "$(git rev-parse --git-path hooks)"/pre-commit
   ```

3. **Preflight without committing.**
   ```bash
   .venv/bin/python scripts/popdd_verify.py --staged
   ```
   `ruff` runs **repo-wide** (`scripts/popdd_verify.py:166`), so one unformatted file anywhere
   walls every commit in every worktree.

4. **Run the suite in the background.** Anything over ~30 s is backgrounded, always. Two real
   timings: on clean `main` the python lane measured 1.7 s of ruff plus 445.5 s of pytest,
   3,925 passed and 3 skipped — 7m25s against the 2,400 s ceiling at `popdd_verify.py:86`. A
   merged tree on 2026-08-16, timed while four CI jobs shared the box, measured 1,281.41 s, 4,612
   passed and 3 skipped. Both pass. **Do not quote either number as current — time it again.**

5. **Narrow the run while iterating.** `scripts/test_impacted.py` selects by diff.

6. **Prove the change against the daemon, not against a unit test alone.** For scheduler and moat
   changes, run the probe and quote the green line.

### 8.2 What catches which mistake

| Mistake | Caught by |
|---|---|
| Unformatted or unlinted code anywhere in the repo | `ruff` inside `popdd_verify.py:166` |
| A new swallowed failure | the ratchet, which fails on a rise |
| A store path bound at import | `tests/unit/test_paths.py` |
| A test that writes to the real ledger | `tests/unit/test_ledger_fence.py` |
| A machine-specific assumption | `tests/test_suite_is_machine_independent.py` |
| A .NET regression | the `dotnet` CI job (`.github/workflows/ci.yml:569`) |
| A storefront regression | `nextjs` (:616) and `ops-console` (:686) jobs |
| A broken doc reference | `scripts/doc_lint.py` against `docs/doc_lint_baseline.json` |

CI job ids for reference: `changes:150`, `guard:267`, `python:339`, `engine:488`, `dotnet:569`,
`nextjs:616`, `ops-console:686`, `ci-ok:748`; concurrency group at `:112`; env
`PYTHON_VERSION: "3.14"`, `DOTNET_VERSION: "9.0"`, `PYTEST_XDIST_AUTO_NUM_WORKERS: "3"`.

### 8.3 Traps that waste a session

- **`pytest` exits 0 when it collects nothing.** Check the collected count, not the exit code.
- **`dotnet test` has reported exit 0 while failing.** Read the summary line.
- **`cmd | tail` reports tail's status.** Capture the real one first.
- **`grep -r` walks 169,226 files in this estate** and orphans to PPID 1 when cancelled. Use `rg`.
- **The shell is zsh.** Wrap any loop or list script in `bash -c`.
- **`git -C repo` loses to an inherited `GIT_DIR`.**
- **Bash cwd persists between calls in an agent session**, which makes a later relative grep
  vacuous. Use absolute paths.
- **Production does not run from this checkout.** It runs from
  `/Users/chidionyema/Documents/code/prospector-live`, detached at `origin/main`. Editing a branch
  here cannot change what production executes. Probe with
  `.venv/bin/python scripts/live_checkout.py`; roll forward with `--update`, which refuses a live
  checkout carrying local changes.

---

## 9. Open gaps and debt

**G1 — `paths.store_root()` and `config.store_root()` disagree, and production is split.** (§5.2)
Cost: under an hour. Make `paths.store_root()` fall back to `PROSPECTOR_STORE_DIR`, or delete it
and route its callers to `config.store_root()`. Keep `paths.py`'s per-call resolution and
`config.py`'s variable name. Add one test asserting the two agree under `PROSPECTOR_STORE_DIR`,
then clean up the 14 leaked files under `/app/store` and fix the false comment at
`deploy/engine/Dockerfile:74`. **Highest damage per hour in the codebase.**

**G2 — `CLAUDE.md` says the non-critical chain is `minimax` alone; `config.yaml:136` reads
`[minimax, minimax_m27]`.** Cost: five minutes to correct the prose, or a decision if the second
tier was not intended. Prose and config disagreeing about the roster is how a session spends an
hour debugging the wrong brain.

**G3 — `_DENSE_REWARD_COMPOSITE_MAX` changed 6.0 → 5.0 on 2026-08-10** (`models.py:22`) with no
migration. Any composite stored before that date is on a different scale. Cost: an afternoon to
stamp a scale version into `Dossier` and make comparisons refuse to cross it. `HYPOTHESIS:`
`tools/l8_grade.py` and `tools/generation_survival.py` compare across the break. Check: grep them
for composite comparisons and look at the date range of their inputs.

**G4 — `gemini_cli.py` and `GeminiGroundingProvider` are in tree with no config selecting them.**
Cost: ten minutes to delete, or a comment saying why they stay. Dead adapters are how
`_build_operator` ends up needing a `ValueError` for each removed one.

**G5 — Two `STANDARD*COMPUTE_API_KEY` secret names exist on `prospector-hermes`** while
`standardcompute` was deleted from this repo on 2026-08-15. Cost: ten minutes to unset both after
confirming hermes does not use them.

**G6 — `tests/unit/test_paths.py` does not cover the invariant it exists to protect.** It proves
`paths.py` resolves per call; it does not prove `paths.py` and `config.py` agree. That gap is
exactly G1. Fixing G1 without adding that assertion leaves the trap armed for the next module.
Cost: ten lines, inside G1's hour.

---

## 10. Where to look next

| Question | Path or command |
|---|---|
| How the deployed units connect | [`architect.md`](architect.md) |
| The estate spine | [`../ESTATE_MAP.md`](../ESTATE_MAP.md), `scripts/estate_map.py` |
| The eight steps | `RUN.md`, then `prospector/run.py:1494` |
| Every tick gate | `prospector/scheduler/run_scheduled.py:1658-1877` |
| Every contract | `prospector/models.py` (573 lines — read it whole) |
| What "backlog" means | `prospector/run.py:2547 drainable()` |
| Which brains may rule | `config.yaml:81`, `prospector/operator.py:1451` |
| Provider health and benching | `prospector/errors.py:134`, `prospector/health.py:54, :130` |
| The money rail | `prospector/bridge.py`, `store_platform/src/Store.Api/Services/FulfilmentService.cs` |
| Pack rendering rules | `docs/PACK_NARRATIVE_PROGRAM.md`, the 17 `prospector/pack_*.py` modules |
| Storefront spec | `docs/SITE_SPEC_PROGRAM.md` |
| Cost measurements | `docs/COST_PROGRAM.md` |
| Is production current? | `.venv/bin/python scripts/live_checkout.py` |
| The gate, without committing | `.venv/bin/python scripts/popdd_verify.py --staged` |

---

*Measured 2026-08-18 against the worktree at `192aa0e4`. Re-run §0 before quoting any number here.*
