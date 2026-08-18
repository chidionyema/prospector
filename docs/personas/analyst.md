# Analyst

**What this is.** A full audit of the data Prospector writes and the judgement it encodes, so you can answer "why did this idea die?" from disk rather than from anyone's recollection.
**Read this if** you must explain a kill, defend a pass rate, tune a threshold, or check whether a number someone quoted is still true.
**Every figure below was measured on 2026-08-18** against `/Users/chidionyema/Documents/code/prospector/store`, and the command that produced it is printed beside it.

Siblings: [machine-learning-engineer.md](machine-learning-engineer.md) (how the models are prompted and routed), [data-engineer.md](data-engineer.md) (how the store is written), [founder.md](founder.md), [product-manager.md](product-manager.md), [finance.md](finance.md), [ops.md](ops.md), [qa-test-engineer.md](qa-test-engineer.md). Estate context: [../ESTATE_MAP.md](../ESTATE_MAP.md).

---

## 0. The short answer to "why did this idea die?"

An idea dies for one of three structurally different reasons, and confusing them is the most common analytical error in this system.

1. **A hard gate fired.** A named check returned `refuted` with cited evidence, and its confidence cleared `thresholds.confidence_floor`. This is an *evidentiary* kill. `prospector/kill_filter.py:20-51`.
2. **A PASS-side floor could not be met.** No hard gate fired. The candidate simply never assembled enough grounded support to be publishable: `moat_ungrounded`, `source_or_die`, or `min_composite`. `prospector/dossier.py:196-235`, `prospector/pass_ceiling.py:59-100`.
3. **It was deferred, not killed.** Retrieval or the moat was unavailable. `prospector/dossier.py:113-147`. A defer is not a verdict about the idea.

Measured split over the 2,698 kill dossiers on disk today: category 1 accounts for **516 kills (19.1%)**, category 2 for **2,042 (75.7%)**, and the adversarial pass for **140 (5.2%)**. Three quarters of all kills in this system are *failures to prove*, not *proofs of failure*. If you report "the filter killed it", you are wrong three times out of four; it declined to publish it.

---

## 1. Complete inventory: where the data lives

### 1.1 The canonical store

There is exactly one store. Both launchd plists pin `PROSPECTOR_STORE_DIR` to `/Users/chidionyema/Documents/code/prospector/store` even though production code runs from `prospector-live` (project `CLAUDE.md`, "Where production runs"). The resolver is `config.store_root()`; `prospector/health.py:31` imports it rather than deriving a path from `__file__`.

| Path | What it is | Live size (measured 2026-08-18) |
|---|---|---|
| `store/dossiers/*.kill.json` | One file per KILL | 2,698 |
| `store/dossiers/*.pass.json` | One file per PASS | 108 |
| `store/dossiers/*.lint.json` | Pack-linter receipts, **not** dossiers | 123 |
| `store/dossiers/*.json` total | | 2,929 |
| `store/prospector.db` | SQLite index over dossiers, table `dossiers` | 2,995 rows, 2,600,960 bytes |
| `store/prospector.jsonl` | Append-only telemetry + spend ledger | 907,977 lines, 270,339,022 bytes |
| `store/listings/*.json` | Published catalogue rows | 119 |
| `store/listings_archive/` | Retired listings | — |
| `store/golden_runs/` | One JSON per golden-set evaluation run | see the ML persona |
| `store/scheduler/` | Daemon state: heartbeats, drains, alerts, `PAUSE` switches | 20+ files; `PAUSE` and `PAUSE_GENERATION` absent today |
| `store/provider_health.json` | Moat brain dead-marks | see the ML persona |
| `store/provider_health_noncritical.json` | Cheap-chain dead-marks | `{}` |
| `store/_cache/` | Retrieval disk cache, `retrieval.py:46` | — |
| `store/prescreen_shadow/` | Shadow log of the wired-off embedding prefilter | — |
| `store/numeric_citation_shadow/` | Shadow log of the numeric-citation check | — |
| `store/markets/<code>/READINESS.json` | Per-market calibration gate output | — |
| `store/generation_metrics.jsonl` | Generation-side counters | — |
| `store/run_metrics.db`, `store/self_modifications.db` | 28,672 / 24,576 bytes, last written 2026-08-02 | stale |

Command that produced the file counts:

```bash
cd /Users/chidionyema/Documents/code/prospector
ls store/dossiers/*.kill.json | wc -l    # 2698
ls store/dossiers/*.pass.json | wc -l    # 108
ls store/dossiers/*.lint.json | wc -l    # 123
ls store/listings/*.json      | wc -l    # 119
wc -l store/prospector.jsonl             # 907977 (measured 907977 by python line count)
```

**Trap already paid for:** `store/dossiers/*.json` is *not* the dossier population. 123 of those 2,929 files are `*.lint.json` pack-linter receipts with a completely different schema (`ok`, `readability_grade`, `house_spec`, `human_register`) and no `decision` field at all. A glob of `*.json` minus `*.kill.json` gives 231, which reads as "231 passes" and is wrong by a factor of 2.1. The real pass count is 108. Always filter on the `decision` key, never on the filename.

### 1.2 The `dossiers` table

```
sqlite3 store/prospector.db "select decision, count(*) from dossiers group by 1 order by 2 desc"
kill|2842
pass|108
defer|45
```

Columns (`PRAGMA table_info(dossiers)`): `candidate_id, title, decision, gate_fired, composite, created_at, reverify_due_at, path, one_liner, ambition_tier, structural_form, provisional, dense_reward, adversarial_confidence, persona, retrieval_degraded, market, tombstone, audience, seed_kind, lease_owner, lease_until`.

**The index and the disk disagree, and the difference is real information.** The table holds 2,842 kills; disk holds 2,698 kill files. It holds 45 defers; disk holds **zero** defer files. Two consequences you must carry into any analysis:

- A `defer` row exists only in the index. There is no defer dossier to read. If you count kills from disk you will under-count by 144 and you will silently drop every defer.
- 45 candidates are parked awaiting `vet --resume`. They are neither killed nor passed. Any "kill rate" that divides by disk files alone excludes them.

HYPOTHESIS: the 144-row gap is dossiers whose files were pruned or tombstoned while the index row survived. The check that would confirm or kill it: `sqlite3 store/prospector.db "select count(*) from dossiers where decision='kill' and tombstone is not null"` and, for each `path` in the table, test existence on disk.

### 1.3 Listing files

119 files under `store/listings/`, and their schema is thin. Measured keys across all of them: `candidate_id, catalog, market, published_via, title, verified_at`. There is **no price, no tier and no composite in a listing file** — every listing row measured `ambition_tier = '?'` because the field does not exist. Price and sellability live in the store platform's catalogue, not here. Do not try to analyse pricing from `store/listings/`.

108 passes on disk against 119 listing files means listings outnumber passes. HYPOTHESIS: listings survive the deletion or retirement of their dossier, or some listings came from `replicate` runs across markets. Check: join `store/listings/*.json` `candidate_id` against `select candidate_id from dossiers` and list the orphans.

---

## 2. Every gate, with its config line and its shipped value

All line numbers are `config.yaml` in the repo root, read 2026-08-18.

### 2.1 Thresholds — `config.yaml:496`

| Key | Line | Value | Which side it governs |
|---|---|---|---|
| `confidence_floor` | 515 | `0.4` | **Kill side only.** A `refuted` verdict only hard-kills when its confidence clears this. |
| `min_supported_confidence` | 525 | `0.3` | **Pass side only.** A `supported` check only counts as grounded above this. |
| `min_composite_to_pass` | 526 | `2.5` | Pass side. Composite floor. |

The two confidence levers are deliberately decoupled (`config.yaml:516-524`), so tightening publication never loosens killing. Conflating them is the single easiest way to misread this system: a check at confidence 0.35 is **too weak to kill on** and **strong enough to count toward a pass**.

`confidence_floor` was raised from 0.0 to 0.4 on 2026-08-07 (`config.yaml:503-513`). The measurement that justified it: replaying `store/dossiers/*.kill.json` through the real `kill_filter.apply_gates` freed 66 of the 333 reproducible kills at 0.4, 19.8%, concentrated as incumbency=31, value_durability=16, payer_solvency=7, legality=6, pain_reality=3. The same note records that 0.5 would free 43.2% and says explicitly that this is a product decision, not calibration.

### 2.2 Hard gates — `config.yaml:528`

Evaluated kill-fast in declaration order:

| Order | Check | Killing verdict | Line |
|---|---|---|---|
| 1 | `value_durability` | `[refuted]` | 551 |
| 2 | `incumbency` | `[refuted]` | 552 |
| 3 | `payer_solvency` | `[refuted]` | 553 |
| 4 | `distribution` | `[refuted]` | 554 |
| 5 | `legality` | `[refuted]` | 555 |
| 6 | `pain_reality` | `[refuted]` | 556 |
| 7 | `adversarial_decisive` | `false` (off at top level) | 557 |

Every gate kills on `refuted` and none kills on `unverifiable`. That is the "no killing on silence" rule: `unverifiable` means no matching passage was found, which is evidence about the web, not about the idea.

**The polarity trap, with receipts on disk.** `legality` once killed on `supported`, which inverted it and killed lawful ideas. `config.yaml:539-549` names two dossiers still readable today: `store/dossiers/459b72f3630d21be.kill.json` (killed because heirloom tomatoes are "completely legal to grow, sell, buy, and eat anywhere in the United States") and `store/dossiers/7e603974bcde1e09.kill.json` ("basic gardening work does not require a specific licence"), at confidences 0.43 and 0.42. If you ever see a proposal to set a gate back to `[supported]`, that is the bug, not the fix.

### 2.3 Weights — `config.yaml:558`

| Axis | Weight | Line |
|---|---|---|
| `pain_acuity` | 0.20 | 568 |
| `money_provability` | 0.20 | 569 |
| `automatability` | 0.15 | 570 |
| `distribution` | 0.15 | 571 |
| `defensibility` | 0.25 | 572 |
| `build_feasibility` | 0.05 | 573 |

Sum 1.00. Re-weighted 2026-06-25 (`config.yaml:559-567`): `automatability` + `build_feasibility` used to total 0.30, which paid out for "trivially easy to build" — the same property as "trivially easy to clone" — while `defensibility`, the only moat axis, carried 0.15. A generic AI wrapper was the global maximum of that formula. Clonability reward went 0.30 → 0.20; moat went 0.15 → 0.25.

Composite arithmetic is one line, `prospector/score.py:20-23`:

```python
def composite(scores, weights):
    return round(sum(float(scores.get(ax, 0)) * float(weights.get(ax, 0.0)) for ax in weights), 4)
```

Missing axes count as zero. The maximum reachable composite is 5.0 (all six axes at 5). `passes_composite` is `score.py:68-69`.

### 2.4 Lane overrides — `config.yaml:615`

`active_lanes: [side_hustle, smb, growth, venture]` (`config.yaml:588`). Each lane overrides `hard_gates`, `thresholds` and adds `score_checks` (run and scored, never able to kill).

| Lane | `min_composite_to_pass` | `min_supported_to_pass` | `moat_critical_checks` | Lines |
|---|---|---|---|---|
| `venture` | 2.5 (635) | 2 (636) | inherits default `(value_durability, incumbency)` | 616-640 |
| `side_hustle` | 2.5 (678) | 2 (679) | `[buyer_intent]` (683) | 641-690 |
| `smb` | 2.6 (744) | — | `[payer_solvency]` (749) | ~700-760 |
| `growth` | 2.9 (795) | — | `[payer_solvency, distribution]` (800) | ~770-805 |

The `moat_critical_checks` override is load-bearing. Hardcoding the venture moat made the smb and side_hustle PASS paths structurally unreachable, because those lanes never run `value_durability` or `incumbency` at all, so every candidate killed on `moat_ungrounded` however well grounded it was (`prospector/dossier.py:206-212`). Proven 2026-06-28 on the Martyn's Law candidate at composite 2.95.

`side_hustle` moves `payer_solvency`, `distribution`, `pain_reality` and `claims_verifiable` from hard gates to `score_checks` (`config.yaml:668-672`). That is why the worked example in §4.2 passes with a **refuted** `payer_solvency`.

### 2.5 The three PASS-side floors — not in `hard_gates`

These produce the majority of kills and appear nowhere in the `hard_gates` block. They are computed in code.

| Gate name | Meaning | Where decided |
|---|---|---|
| `source_or_die` | fewer than `min_supported_to_pass` grounded-supported checks | `dossier.py:225-231`, precomputed by `pass_ceiling.py:81` |
| `moat_ungrounded` | zero of the lane's `moat_critical_checks` was grounded-supported | `dossier.py:217-223`, `pass_ceiling.py:89` |
| `min_composite` | composite below the lane bar, or the theoretical maximum already cannot clear it | `dossier.py:232-235`, `pass_ceiling.py:93` |

`pass_ceiling.SOFT_EXIT_GATES` is exactly those three (`pass_ceiling.py:32`). `pass_impossible_reason` (`pass_ceiling.py:59`) lets the vet stop early once a PASS is arithmetically out of reach, which is a throughput optimisation, not a separate judgement.

**Reporting trap.** `prospector/report.py:105` and five sibling lines read `r.get("gate_fired") or "min_composite"`. A dossier with a **null** `gate_fired` is *labelled* `min_composite` in every report. Do not read a report's `min_composite` count as "the composite gate fired"; read it as "the composite gate fired, or nothing was recorded".

---

## 3. The six scoring axes

`SCORE_AXES` is `models.py:114-115`: `pain_acuity, money_provability, automatability, distribution, defensibility, build_feasibility`. Each is an integer clamped to `[0, 5]` at `score.py:50-51`.

Measured over the 865 dossiers on disk that carry a `score` block:

| Axis | Weight | Mean | Median | Min | Max |
|---|---|---|---|---|---|
| `pain_acuity` | 0.20 | 1.68 | 2.0 | 0 | 5 |
| `money_provability` | 0.20 | 1.11 | 1.0 | 0 | 5 |
| `automatability` | 0.15 | 1.69 | 2.0 | 0 | 5 |
| `distribution` | 0.15 | 1.35 | 1.0 | 0 | 5 |
| `defensibility` | 0.25 | 1.07 | 1.0 | 0 | 4 |
| `build_feasibility` | 0.05 | 1.92 | 2.0 | 0 | 5 |

Two things stand out and both matter.

**`defensibility` never reached 5 in 865 scored dossiers.** Its observed maximum is 4. It also carries the heaviest weight, 0.25. So 0.25 of the composite is capped in practice at 4/5 of its nominal ceiling. HYPOTHESIS: the scoring prompt's rubric for a 5 on defensibility is unreachable for the kind of idea this engine generates. The check that would confirm or kill it: read the axis brief rendered by `score._axes_brief(cfg)` at `score.py:42-44` and the `defensibility` rung definitions, then run twenty candidates with the rubric relaxed and compare the distribution.

**The all-zero fail-safe is in this data.** `score.py:54-62` sets every axis to 0 and `score_failed=True` when the scoring call raises. Those rows are *not* a judgement of 0/5. Measured composite p25 is 0.000 — a quarter of all scored dossiers have a composite of zero, which is the fail-safe, not a scored opinion. **Any mean over composites is contaminated by these.** Exclude `score_failed` before computing an average.

---

## 4. How it actually works: two end-to-end traces

### 4.1 Trace A — a hard-gate kill (`incumbency`, 254 dossiers on disk)

Hop by hop, with the file and line at each step.

1. `run.py` builds the operator chain and calls `verify.verify(...)`, which wraps the run in the market context manager — `verify.py:978-1003`.
2. `_verify_inner` builds the run order from `cfg.hard_gates` — `verify.py:1019`. `price_comparables` is stripped from that order unconditionally — `verify.py:1031`. So the seventh check can never enter the kill-fast loop.
3. If `retrieval.llm_query_gen` is on (`config.yaml:344` = `true`), all queries for all checks are generated in one batched call — `verify.py:1050-1061`. Checks the cheap tier missed are re-generated on the trusted brain before any template fallback.
4. For each check in order, `run_check` runs — `verify.py:721`. It picks a query source (`verify.py:731-759`), fans the queries out over a thread pool (`verify.py:761-782`), dedups by `source_id` (`verify.py:804-808`).
5. If retrieval returned nothing at all, `run_check` short-circuits to `UNVERIFIABLE` at confidence 0.0 **without calling a model** — `verify.py:810-827`. That is why 1,578 checks on disk sit at exactly 0.000 confidence.
6. Otherwise `verdict_for` renders the `verdict` prompt and calls the brain at temperature 0.0 — `verify.py:512-521`.
7. The model's self-reported confidence is discarded. `_calc_confidence(sources, citations, CHECKS[check_name])` computes it from evidence — `verify.py:591`. See §5.3.
8. A `supported` verdict with zero resolvable citations is forced to `UNVERIFIABLE` — `verify.py:583-586`. Source-or-die, enforced per check.
9. Back in the loop, `is_hard_fail(name, res, cfg)` decides — `kill_filter.py:20-51`. It requires, in order: not `price_comparables` (`:28`), not `retrieval_failed` (`:34`), the check is in `gate_map()` (`:36`), the verdict is in that gate's killing list (`:42`), and **finally** `result.confidence >= cfg.thresholds.confidence_floor` (`:51`).
10. First hard fail wins and the loop stops — `verify.py:1152-1160`.
11. `dossier.build(...)` writes the reason string — `dossier.py:148-160`: `"It failed on: {label} — {verdict} (conf {conf:.2f}): {rationale}"`.

Read the ground truth for this path in any `*.kill.json` whose `gate_fired` is a check name. Example measured today: `store/dossiers/ffedf0fac84d90b0.kill.json`, `gate_fired: distribution`, `reason: "It failed on: Can you actually reach the customer? (distribution) — refuted (conf 0.58)..."`, three checks recorded, eleven sources.

### 4.2 Trace B — a PASS, worked end to end

File: `store/dossiers/08b22037fc2afc07.pass.json`. Title: "Care hours cut challenge service for family carers". Lane `side_hustle`, market `uk`.

Eight checks ran:

| Check | Verdict | Confidence | Citations | Role in this lane |
|---|---|---|---|---|
| `buyer_intent` | supported | 0.573 | 3 | hard gate **and** `moat_critical_checks` |
| `currency` | supported | 0.700 | 6 | hard gate |
| `route_to_market` | supported | 0.633 | 4 | hard gate |
| `legality` | supported | 0.612 | 4 | hard gate |
| `claims_verifiable` | supported | 0.717 | 4 | `score_checks`, cannot kill |
| `payer_solvency` | **refuted** | 0.530 | 5 | `score_checks`, cannot kill |
| `distribution` | supported | 0.380 | 2 | `score_checks`, cannot kill |
| `pain_reality` | unverifiable | 0.000 | 0 | `score_checks`, cannot kill |

Hop by hop:

1. `payer_solvency` is `refuted` at 0.530, well above `confidence_floor` 0.4. It did **not** kill, because `side_hustle` moved it to `score_checks` — `config.yaml:672`. `kill_filter.is_hard_fail` returned False at `kill_filter.py:36-38` because the name is not in this lane's `gate_map()`.
2. No hard gate fired, so scoring ran. Axes on disk: `pain_acuity 4, money_provability 1, automatability 3, distribution 3, defensibility 2, build_feasibility 4`.
3. Composite, recomputed by hand against `config.yaml:568-573`:

```
pain_acuity        4 × 0.20 = 0.80
money_provability  1 × 0.20 = 0.20
automatability     3 × 0.15 = 0.45
distribution       3 × 0.15 = 0.45
defensibility      2 × 0.25 = 0.50
build_feasibility  4 × 0.05 = 0.20
                   ---------------
                            = 2.60
```

The stored `composite` field is `2.6`. The recomputation matches exactly. The bar for `side_hustle` is `min_composite_to_pass: 2.5` (`config.yaml:678`), cleared by 0.10.

4. Source-or-die at the pass boundary — `dossier.py:196-215`. Grounded-supported means `verdict == supported` **and** `confidence >= min_supported_confidence` (0.3). Six checks qualify: `buyer_intent, currency, route_to_market, legality, claims_verifiable, distribution` (0.380 clears 0.3 by 0.08). `min_supported_to_pass` is 2. Satisfied.
5. Publish-critical requirement: `moat_critical_checks: [buyer_intent]` (`config.yaml:683`). `buyer_intent` is supported at 0.573. `moat_grounded = 1`. Satisfied.
6. The adversarial pass ran and returned `decisive: false, confidence: 0.2`, with a fully cited kill case naming the poverty of the buyer group. It did not kill, because `side_hustle`'s `adversarial_decisive: false` (`config.yaml:655`) and because `decisive` was False anyway (`verify.py:946-955`).
7. `dossier.py:213-216` writes the reason: `"Survived all gates; composite 2.6000; 6 grounded-supported check(s) (moat grounded: 1)."` — which is exactly the string on disk.

**This example is the whole system in one file.** It shows a refuted check that did not kill, a zero-confidence unverifiable check that did not kill, a composite that clears its bar by 0.10, and a single grounded moat check carrying the publish decision. If you can read this dossier you can read any of them.

Note one gap in it: the eight checks all carry `query_source: null`. This dossier predates the field being populated. 6,318 of 14,006 checks on disk have no `query_source` (measured). Any analysis of query provenance covers only 55% of the corpus.

---

## 5. The numbers, measured

Every table in this section came from one script run on 2026-08-18 over `store/dossiers/*.kill.json` and `*.pass.json`. The reproduction commands are in §9.

### 5.1 The funnel

| Stage | Count | Source |
|---|---|---|
| Dossier rows in the index | 2,995 | `select count(*) from dossiers` |
| — decided `kill` | 2,842 | index |
| — decided `pass` | 108 | index |
| — decided `defer` (parked, no file) | 45 | index |
| Dossier files on disk with a `decision` | 2,806 | file scan |
| Checks recorded across them | 14,006 | file scan |
| Mean checks per dossier | 4.99 (median 6, min 1, max 9) | file scan |
| Listings published | 119 | `ls store/listings/*.json` |

Overall pass rate on disk: **108 / 2,806 = 3.85%**.

By month of `created_at`: 2026-06 → 714 dossiers, 2026-07 → 170, 2026-08 → 1,922.

### 5.2 Kill reasons ranked by frequency

Measured over all 2,698 kill dossiers.

| Rank | `gate_fired` | Count | Share | Category |
|---|---|---|---|---|
| 1 | `moat_ungrounded` | 1,042 | 38.6% | PASS-side floor |
| 2 | `min_composite` | 744 | 27.6% | PASS-side floor |
| 3 | `source_or_die` | 256 | 9.5% | PASS-side floor |
| 4 | `incumbency` | 254 | 9.4% | hard gate |
| 5 | `adversarial_decisive` | 140 | 5.2% | adversarial |
| 6 | `value_durability` | 112 | 4.2% | hard gate |
| 7 | `payer_solvency` | 59 | 2.2% | hard gate |
| 8 | `legality` | 30 | 1.1% | hard gate |
| 9 | `distribution` | 18 | 0.7% | hard gate |
| 10 | `currency` | 14 | 0.5% | hard gate (side_hustle) |
| 11 | `route_to_market` | 13 | 0.5% | hard gate (side_hustle) |
| 12 | `pain_reality` | 9 | 0.3% | hard gate |
| 13 | `buyer_intent` | 7 | 0.3% | hard gate (side_hustle) |

Hard gates total 516 (19.1%). PASS-side floors total 2,042 (75.7%).

**`moat_ungrounded` is the single largest cause of death in this system.** It means the lane's one decisive check was never grounded-supported. It is a retrieval-and-grounding outcome far more than an idea-quality outcome. `config.yaml:1337` records the same finding on the 2026-08-10 batch. Any programme aimed at "better ideas" that does not move this number is aimed at the wrong thing.

### 5.3 Confidence: what the scale actually is

`_calc_confidence` (`verify.py:91-192`) replaces the model's self-report with three deterministic terms:

- citation credit, weight 0.30, `max(fraction_of_retrieved_cited, min(1, cited/3))` — `verify.py:110-136`
- domain diversity, weight 0.40, stepped: 3+ domains → 0.40, 2 → 0.25, 1 → 0.15, 0 → 0.0 — `verify.py:151-171`
- keyword relevance of the best cited passage against the check question, weight 0.30 — `verify.py:173-189`

The nominal range is 0–1. **The observed range is not.** Measured over all 14,006 checks on disk:

| Population | n | min | p10 | p25 | median | p75 | p90 | max | mean |
|---|---|---|---|---|---|---|---|---|---|
| all checks | 14,006 | 0.000 | 0.000 | 0.433 | 0.662 | 0.724 | 0.733 | **0.820** | 0.551 |
| `supported` | 3,079 | 0.130 | 0.370 | 0.460 | 0.600 | 0.700 | 0.730 | 0.800 | 0.569 |
| `refuted` | 662 | 0.000 | 0.350 | 0.417 | 0.580 | 0.680 | 0.717 | 0.812 | 0.542 |
| `unverifiable` | 10,265 | 0.000 | 0.000 | 0.430 | 0.700 | 0.733 | 0.733 | 0.820 | 0.546 |
| the check that fired the gate | 516 | 0.000 | 0.400 | 0.440 | 0.587 | 0.688 | 0.720 | 0.812 | 0.556 |

**No check in the entire corpus has ever scored above 0.820, and only 5 of 14,006 reached 0.80.** A confidence of 0.75 is near the practical ceiling of this scorer, not a middling score. Treating 0.75 as "three quarters certain" is a category error; treat it as roughly the 90th percentile of what this formula can emit.

1,578 checks sit at exactly 0.000. That is the no-evidence short-circuit at `verify.py:810-827` firing before any model call.

Distribution of all 14,006, in 0.05 buckets:

```
0.00-0.05   1578  ######################
0.10-0.15     67
0.15-0.20    130  #
0.20-0.25    163  ##
0.25-0.30     83  #
0.30-0.35    197  ##
0.35-0.40    238  ###
0.40-0.45   1262  #################
0.45-0.50    389  #####
0.50-0.55    123  #
0.55-0.60   1817  #########################
0.60-0.65    882  ############
0.65-0.70   2169  ##############################
0.70-0.75   4235  ############################################################
0.75-0.80    668  #########
0.80-0.85      5
```

The distribution is spiky, not smooth. The 0.70–0.75 bucket holds 30% of all checks. Those spikes are the stepped diversity term at `verify.py:161-171`: a check citing 3+ domains lands on exactly 0.40 from that term, plus a saturating 0.30 citation term, plus a relevance tail. **Confidence in this system is close to a discrete ladder, not a continuous score.** Do not fit a continuous model to it and do not read fine differences between 0.70 and 0.72 as meaningful.

Citations per supported check: mean 3.59, median 3, max 10, and **zero supported checks have zero citations** — the source-or-die downgrade at `verify.py:583-586` is doing its job with no exceptions in 3,079 cases.

### 5.4 The calibration note is out of date, and I can date the drift

`config.yaml:517-524` justifies `min_supported_confidence: 0.3` with a measurement taken 2026-06-25: "the LIVE distribution over 504 supported checks in store/dossiers/: median=0.43, p25=0.40, p10=0.30, max=0.79 — the live scale is COMPRESSED (~0.43), not 0-1", and states "0.5 would void 76% of real supported checks".

Measured today, split by the month the dossier was created:

| Month | supported checks | median confidence | mean |
|---|---|---|---|
| 2026-06 | 493 | **0.430** | 0.438 |
| 2026-07 | 326 | 0.580 | 0.528 |
| 2026-08 | 2,260 | **0.630** | 0.604 |

The 2026-06 median is 0.430, matching the config note almost exactly (their 504 checks against my 493 — the small gap is dossiers deleted since). **The note was right when written and is now stale by 0.20.** Over all 3,079 supported checks today:

| Floor | supported checks voided | share |
|---|---|---|
| 0.3 (shipped) | 181 | 5.9% |
| 0.4 | 391 | 12.7% |
| 0.5 | 906 | **29.4%** |

The note's claim that 0.5 "would void 76% of real supported checks" is no longer true; today it is 29.4%. The shift is explained by `_calc_confidence` being loosened on 2026-08-15 — the diversity credit for a lone domain went 0.10 → 0.15 (`verify.py:161-171`) and the citation term became `max(fraction, saturating)` (`verify.py:130-136`), and both changes raise scores and neither can lower one.

**Consequence:** the shipped floor of 0.3 now trims 5.9% rather than the intended bottom-10% tail. It is looser than designed. That is a calibration decision for the founder, not a defect, but it should be decided knowingly. Do not quote the 76% figure again.

### 5.5 Verdicts

| Verdict | Count | Share |
|---|---|---|
| `unverifiable` | 10,265 | 73.3% |
| `supported` | 3,079 | 22.0% |
| `refuted` | 662 | 4.7% |

`retrieval_failed` checks on disk: **0**. Degraded checks: 300. That zero is correct by construction, not luck: a `retrieval_failed` check fires the DEFER gate at `verify.py:1134-1151`, and a defer never writes a dossier file (`dossier.py:113-147` sets `decision = DEFER` and the 45 such rows live only in the index).

By check name:

| Check | n | supported | refuted | unverifiable | refute rate |
|---|---|---|---|---|---|
| `legality` | 2,331 | 425 | 32 | 1,874 | 1.4% |
| `payer_solvency` | 2,199 | 259 | 78 | 1,862 | 3.5% |
| `distribution` | 2,141 | 513 | 21 | 1,607 | 1.0% |
| `pain_reality` | 1,682 | 475 | 15 | 1,192 | 0.9% |
| `value_durability` | 1,573 | 393 | 132 | 1,048 | 8.4% |
| `incumbency` | 1,463 | 101 | **300** | 1,062 | **20.5%** |
| `buyer_intent` | 1,107 | 381 | 9 | 717 | 0.8% |
| `currency` | 633 | 261 | 30 | 342 | 4.7% |
| `route_to_market` | 480 | 146 | 17 | 317 | 3.5% |
| `claims_verifiable` | 397 | 125 | 28 | 244 | 7.1% |

**`incumbency` is the outlier by a wide margin.** It refutes at 20.5%, more than double the next check, and it is the only check where refuted (300) outnumbers supported (101). It is also the top hard-gate killer at 254 kills. Two readings are possible and this data cannot separate them: either the market really is crowded, or the check's disconfirm query template reliably surfaces *some* competitor for any idea and the model reads that as a dominant incumbent. `_DISCONFIRM_TEMPLATES` is `verify.py:239-251`. The 2026-06-15 war room flagged `incumbency` as over-restrictive, and the E11 replay freed 31 incumbency kills at the 0.4 floor — more than any other gate (`config.yaml:509-510`).

### 5.6 Composite distribution

Only 865 of 2,806 dossiers carry a `score` block. The other 1,941 died on a hard gate before scoring ran — kill-fast means no score is computed once a gate fires.

| n | min | p10 | p25 | median | p75 | p90 | max | mean |
|---|---|---|---|---|---|---|---|---|
| 865 | 0.000 | 0.000 | 0.000 | 1.650 | 2.300 | 2.700 | **3.750** | 1.383 |

158 of 865 (18.3%) reach 2.5 or above. The observed maximum in the entire corpus is 3.750 against a theoretical maximum of 5.0. `growth`'s bar is 2.9 and `venture`'s is 2.5; the highest composite ever recorded is 3.75, so the headroom above the strictest lane bar is 0.85 out of 5.

**The p25 of 0.000 is the `score_failed` fail-safe**, not a set of terrible ideas (`score.py:54-62`). Exclude it before averaging.

### 5.7 Pass rates by lane and market

By `ambition_tier`, from disk:

| Lane | n | pass | pass rate | kill |
|---|---|---|---|---|
| `side_hustle` | 425 | 35 | **8.24%** | 390 |
| `venture` | 329 | 13 | 3.95% | 316 |
| `growth` | 434 | 15 | 3.46% | 419 |
| `smb` | 595 | 19 | 3.19% | 576 |
| blank/`?` | 1,023 | 26 | 2.54% | 997 |

`side_hustle` passes at 2.6× the rate of `smb`. Its bar is not lower in composite terms (2.5 vs 2.6, a 0.1 difference) — the difference is structural: `side_hustle` moves four checks from hard gates to `score_checks` (`config.yaml:668-672`) and requires only `buyer_intent` grounded (`config.yaml:683`). Fewer ways to die, not an easier score.

The 1,023 rows with a blank tier are pre-lane dossiers. The index agrees: `('', 'kill', 998)` and `('', 'pass', 26)` from `select ambition_tier, decision, count(*) from dossiers group by 1,2`.

By market (top rows by volume):

| Market | n | pass | pass rate |
|---|---|---|---|
| `uk` | 1,948 | 69 | 3.54% |
| `us-il` | 158 | 3 | 1.90% |
| `us` | 142 | 13 | 9.15% |
| `us-ga` | 137 | 13 | 9.49% |
| `us-ca` | 98 | 2 | 2.04% |
| `us-oh` | 96 | **0** | 0.00% |
| `us-pa` | 56 | 2 | 3.57% |
| `us-fl` | 55 | 2 | 3.64% |
| `us-tx` | 50 | 3 | 6.00% |
| `us-ny` | 46 | **0** | 0.00% |

Two markets have produced zero passes across 142 attempts between them. HYPOTHESIS: their `authority_domains` list is thin, so `_calc_confidence`'s diversity term (`verify.py:151-171`) cannot reach the 3-domain step and `moat_ungrounded` fires. Check: `python3 -c "import json,glob,collections; ..."` counting `gate_fired` restricted to `us-oh` and `us-ny`, then compare against the market's `authority_domains` in the market config.

### 5.8 The ledger

`store/prospector.jsonl`, 907,977 lines, 270 MB. First timestamp `2026-06-15 00:46:11,080`, last `2026-08-18 13:58:36,919`.

| Record kind | Count |
|---|---|
| unlabelled (no `event`/`kind`/`type` key) | 469,930 |
| `latency` | 396,437 |
| `spend` | 33,553 |
| `listing_page` | 1,710 |
| `teaser_social` | 1,577 |
| `launch_email` | 1,563 |
| `seo_preview` | 1,431 |
| `build_spec` | 590 |
| `gtm_plan` | 569 |
| `ops_plan` | 568 |
| `financial_model` | 49 |

Provider tallies (top): `minimax/MiniMax-M3` 17,379, `deepseek/deepseek-v4-pro` 11,337, `claude_cli` 7,438, `minimax` 5,667, `deepseek` 1,358, `ddg` 1,347, `standardcompute/standardcompute` 1,017, `exa` 916, `searxng` 508, `gemini_cli` 333, `cursor_cli` 327.

**Do not quote a spend total from this file naively.** Summing every numeric `cost_usd`/`cost` field across all 907,977 lines gives 4546.7154, but not one of those records also carries a `provider` field, so the per-provider breakdown is empty. The two shapes do not overlap. HYPOTHESIS: the cost field is a running cumulative total re-stamped on each record rather than a per-call increment, which would make the sum a large multiple of real spend. The check that would settle it: `python3 -c` reading the first 50 records that carry a cost field and printing whether the value increases monotonically. Until that is run, treat 4546.7154 as **unverified** and use `prospector/ops/spend.py` or the console's money page for a spend figure instead.

Related trap already recorded in this estate: transcript totals double-count per record. The lesson transfers directly.

---

## 6. How to read a dossier, field by field

Top level of a `*.kill.json` or `*.pass.json` (`prospector/models.py:559-573` writes it):

| Field | Type | What it means | Trap |
|---|---|---|---|
| `candidate` | object | The idea as generated: `title`, `one_liner`, `hypothesis`, `who_pays`, `why_now`, `tags`, `candidate_id`, `structural_form`, `ambition_tier`, `market`, `refinement_history` | `tags` is a free-form dict; it also carries `price_comparables` output (`verify.py:1211-1233`) |
| `ambition_tier` | string | The lane it was judged against | Blank on 1,023 pre-lane dossiers |
| `decision` | `kill`/`pass` | The verdict | `defer` never reaches disk |
| `gate_fired` | string or null | Why it died | Null is *labelled* `min_composite` by `report.py:105` |
| `reason` | string | Plain-English explanation, written by `dossier.py:148-235` | Everything before the first `:` is stripped by `adaptive.py` — keep that contract |
| `checks` | list | One entry per check that ran | Length varies 1–9; kill-fast means a kill has fewer |
| `adversarial` | object or null | `kill_case`, `decisive`, `confidence`, `citations`, `objections` | Null when a hard gate fired first |
| `score` | object or null | `scores` (six axes), `justification`, `composite`, `score_failed` | Null on 1,941 of 2,806; all-zero means `score_failed` |
| `model_version`, `provider_chain` | string | Which brain chain ruled, e.g. `fallback(minimax+claude_cli)` | Historical chains include removed tiers |
| `created_at`, `reverify_due_at` | ISO 8601 | Written and re-vet-due timestamps | Re-vet window is 30 days in every sample checked |
| `provisional` | bool | Ruled by a brain outside `moat_primary()` | **All 2,806 read False** |
| `dense_reward` | float | Generation-feedback signal | Not a quality score; do not rank on it |
| `sources` | list | Every retrieved passage: `source_id`, `url`, `text`, `published_at`, `query`, `fetched_at`, `archived_url` | `published_at` is frequently null, which is why `currency` rules only on dated passages |

Each entry in `checks`:

| Field | Meaning | Trap |
|---|---|---|
| `check_name` | one of the ten in `models.py CHECKS` | |
| `verdict` | `supported` / `refuted` / `unverifiable` | Only `refuted` can kill |
| `confidence` | `_calc_confidence` output, `verify.py:591` | Ceiling observed 0.820, not 1.0 |
| `rationale` | the model's prose, clipped at `verify.py:644` | An empty rationale forces DEFER (`verify.py:662-672`) |
| `citations` | `source_id`s the model cited | A supported check with zero is downgraded to unverifiable |
| `sources` | the cited subset, or all if none resolved (`verify.py:709`) | So `len(sources)` is not "sources retrieved" |
| `queries` | the search queries used | |
| `query_source` | `llm_batched` / `llm_percheck` / `template` / `template_fallback` / `entity` | **Null on 6,318 of 14,006 checks** |
| `degraded` | retrieval was thin or synthesized sources were stripped | 300 on disk |
| `retrieval_failed` | infra failure; fires DEFER | 0 on disk, by construction |
| `provider` | which brain served this check | |
| `provisional` | brain outside `moat_primary()` | |

Measured `query_source` where present: `llm_batched` 7,684, `llm_percheck` 3, `template` 1. The batched path is effectively the only live path.

---

## 7. Failure modes

Concrete breakages, preferring ones that happened here.

| Symptom | Root cause | Fix |
|---|---|---|
| "231 passes" reported | Counted `*.json` minus `*.kill.json`; 123 of those are `*.lint.json` pack-linter receipts with no `decision` field | Filter on the `decision` key. Real count 108. Measured 2026-08-18 |
| Lawful ideas killed on `legality` | Gate was `[supported]`, inverting the check's positive polarity | Gate is `[refuted]` (`config.yaml:555`). Receipts still on disk: `459b72f3630d21be.kill.json`, `7e603974bcde1e09.kill.json` |
| A fully grounded PASS killed as `moat_ungrounded` | `_calc_confidence` took most of its value from citation *volume*; a check citing one strong source scored 0.238 against the 0.30 floor | Citation term is now `max(fraction, saturating/3)` and a lone domain earns 0.15 (`verify.py:130-136`, `verify.py:161-171`). The killed candidate is named at `verify.py:119-122` |
| smb and side_hustle could never pass | `moat_critical_checks` was hardcoded to the venture pair, and those lanes do not run those checks | Lane-level override (`config.yaml:683`, `:749`, `:800`). Proven 2026-06-28 on Martyn's Law at composite 2.95 (`dossier.py:206-212`) |
| Nine "passes" with every check unverifiable at confidence 0.0 and zero sources | Composite alone decided PASS during the 2026-06-16 grounding outage | Source-or-die at the pass boundary (`dossier.py:196-215`) |
| A dossier that reads as fully reasoned but every check says "Verdict call failed; fail-safe." | A raising verdict call contributed `unverifiable` to the gates instead of deferring | `retrieval_failed=True` fires DEFER (`verify.py:554-570`, gate at `verify.py:1134-1151`). The original receipt is `store/dossiers/2102bacc6dd75cf9.kill.json` |
| Report shows a large `min_composite` bucket that does not match the composite data | `report.py:105` reads `gate_fired or "min_composite"`, so nulls are relabelled | Count `gate_fired is null` separately before trusting the bucket |
| A "kill rate" that omits 45 candidates | Defers exist only in `prospector.db`; they write no file | Read the index, not the directory, for any rate |
| Mean composite looks catastrophically low | 25% of scored dossiers are the `score_failed` all-zero fail-safe | Exclude `score_failed` (`score.py:54-62`) before averaging |
| Quoting "0.5 would void 76% of supported checks" | True on 2026-06-25, measured 29.4% today after the 2026-08-15 scorer loosening | Re-measure; see §5.4 |
| Comparing confidences as if 0–1 | Observed max across 14,006 checks is 0.820; the scale is a stepped ladder | Read percentiles from §5.3, not the nominal range |
| A spend total quoted from `prospector.jsonl` | Cost-bearing records carry no provider; the sum is unvalidated | Use `prospector/ops/spend.py` / the console money page |

---

## 8. Invariants

Rules that must not break, and what happens when they do.

1. **A KILL is grounded in cited disconfirming evidence, never in silence.** `unverifiable` is not a killing verdict for any gate (`config.yaml:551-556`). Break it and the engine kills every candidate whose evidence is merely hard to find — which under kill-fast means `value_durability` executes almost everything before another gate runs (`config.yaml:530-533`).
2. **A `supported` verdict with zero resolvable citations is downgraded to `unverifiable`.** `verify.py:583-586`. Measured: zero of 3,079 supported checks violate this. Break it and ungrounded passes reach the catalogue.
3. **A failed call defers; it never contributes evidence.** `verify.py:554-570` and `verify.py:1134-1151`. Break it and outages are recorded as reasoned kills.
4. **`price_comparables` can never kill.** Enforced twice: `kill_filter.py:28-29` and `verify.py:1031`. "No price page on the open web" is a fact about the web.
5. **The kill-side and pass-side confidence floors stay decoupled.** `confidence_floor` 0.4 and `min_supported_confidence` 0.3 are separate keys (`config.yaml:515`, `:525`). Merging them means tightening publication loosens killing.
6. **Weights sum to 1.00.** `config.yaml:568-573`. Break it and composites are no longer comparable across time or lanes.
7. **A DEFER never publishes and never counts as an evidentiary kill.** `dossier.py:113-147`.
8. **The gate order is kill-fast and cheapest-decisive-first.** `verify.py:1019` builds it from `hard_gates` declaration order. Reordering changes which gate gets credited for a kill even when the outcome is identical — so any time series of `gate_fired` counts is broken by a reorder.
9. **A provisional ruling never publishes on PASS.** `run.py:864`, `operator.py:1509-1514`. All 2,806 dossiers on disk read `provisional: false`.

---

## 9. How to run an analysis yourself

Read-only. None of these write to the store.

```bash
cd /Users/chidionyema/Documents/code/prospector

# The catalogue, costs and trend — no model calls at all
.venv/bin/python -m prospector.run report
.venv/bin/python -m prospector.run report --min-composite 2.5

# Index-level truth, including defers that have no file
sqlite3 store/prospector.db "select decision, count(*) from dossiers group by 1 order by 2 desc"
sqlite3 store/prospector.db "select ambition_tier, decision, count(*) from dossiers group by 1,2 order by 1,3 desc"
sqlite3 store/prospector.db "select gate_fired, count(*) from dossiers where decision='kill' group by 1 order by 2 desc limit 15"
sqlite3 store/prospector.db "select market, decision, count(*) from dossiers group by 1,2 order by 1"

# Estate and daemon state
.venv/bin/python scripts/ops_status.py
.venv/bin/python scripts/store_audit.py
.venv/bin/python scripts/live_checkout.py        # is production running current code?

# Calibration alarms over the catalogue — free, no model calls
.venv/bin/python -m prospector.run diagnose
```

Kill reasons, verdict mix and confidence percentiles in one pass:

```python
# .venv/bin/python - <<'PY'
import json, glob, collections, statistics
gates, verd, conf = collections.Counter(), collections.Counter(), []
tier = collections.defaultdict(collections.Counter)
for p in glob.glob("store/dossiers/*.kill.json") + glob.glob("store/dossiers/*.pass.json"):
    d = json.load(open(p))
    if "decision" not in d:            # skip *.lint.json shaped files
        continue
    if d.get("gate_fired"):
        gates[d["gate_fired"]] += 1
    tier[str(d.get("ambition_tier") or "?")][d["decision"]] += 1
    for c in d.get("checks") or []:
        verd[c["verdict"]] += 1
        if isinstance(c.get("confidence"), (int, float)):
            conf.append(c["confidence"])
print(gates.most_common())
print(verd.most_common())
conf.sort()
print("n", len(conf), "median", statistics.median(conf), "max", conf[-1])
for t, row in tier.items():
    n = sum(row.values())
    print(t, n, row.get("pass", 0), round(100 * row.get("pass", 0) / n, 2))
# PY
```

Reproduce every number in §5 at once: `/private/tmp/claude-501/.../scratchpad/measure.py` is the script that produced this document's tables. It takes about 90 seconds over 2,929 files.

Replay historical kills through the *current* gate logic — the only honest way to test a threshold change:

```bash
.venv/bin/python tools/experiments/e11_confidence_floor.py
```

This is what produced the "66 of 333 freed at 0.4" figure at `config.yaml:503-513`. Note its own caveat, recorded in this estate: replaying kills only reproduces *hard* gates. It cannot replay `moat_ungrounded`, `min_composite` or `source_or_die`, which is 75.7% of all kills. Any threshold experiment run this way is measuring the smaller fifth of the problem.

---

## 10. Open gaps and debt

| Gap | Why it costs you | Cost to close |
|---|---|---|
| **No calibration measurement exists.** Nothing compares a predicted confidence to an observed outcome. No Brier score, no reliability curve. `verify.py:93` states the design deliberately replaces model self-calibration with a deterministic formula, but the formula itself is never validated against ground truth. | Every threshold in §2.1 is set against a *distribution*, never against accuracy. We know 0.4 frees 19.8% of kills; we do not know whether those 66 candidates were good | Medium. Needs labelled outcomes. The golden set (9 cases) is the only labelled data and is far too small. Cheapest first step: label the 108 passes and 119 listings by whether they sold, then bin by the moat check's confidence |
| **`e11`-style replay covers only hard gates**, 19.1% of kills | Threshold experiments systematically ignore the dominant failure mode | Low-medium. Extend the replay harness to call `pass_ceiling.pass_impossible_reason` and `dossier.build` so PASS-side floors reproduce |
| **`min_supported_confidence` drifted from its calibration** — the floor was set to trim the bottom 10% and now trims 5.9% (§5.4) | The pass-side floor is looser than intended and nobody decided that | Trivial to measure (done, §5.4). The decision is the founder's |
| **`us-oh` and `us-ny` have zero passes over 142 attempts** | Two markets may be structurally unable to pass and are still being generated into | Low. Restrict the §5.2 kill-reason count to those markets and compare against their `authority_domains` |
| **6,318 of 14,006 checks have no `query_source`** | Query-provenance analysis covers 55% of the corpus | None to close forward; historical rows cannot be backfilled. State the coverage whenever you use the field |
| **`defensibility` never scored above 4 in 865 dossiers**, while carrying the heaviest weight | 0.25 of the composite is practically capped at 80% | Low. Read the rubric at `score.py:42-44` and test twenty candidates |
| **144 index rows have no dossier file** | Every disk-based count is short by 144 | Low. Join `path` against the filesystem |
| **The ledger's cost field cannot be attributed to a provider** | No per-brain cost analysis is possible from `prospector.jsonl` | Medium. Requires the emitter to stamp `provider` on cost records |
| **`store/run_metrics.db` and `store/self_modifications.db` last written 2026-08-02** | Two data sources look live and are 16 days stale | Trivial to confirm: `ls -la store/*.db` |

---

## 11. Where to look next

Judgement, in the order it is applied:

```
prospector/verify.py:721      run_check — one check end to end
prospector/verify.py:91       _calc_confidence — where every confidence number comes from
prospector/verify.py:1019     the run order, built from hard_gates
prospector/verify.py:1134     the DEFER gate
prospector/kill_filter.py:20  is_hard_fail — the four conditions a kill must meet
prospector/pass_ceiling.py:59 pass_impossible_reason — the three PASS-side floors
prospector/dossier.py:100     the decision and every reason string
prospector/score.py:20        the composite, in three lines
prospector/models.py:111      DEFAULT_CHECKS, SCORE_AXES, CHECKS (the question text)
```

Configuration:

```
config.yaml:496   thresholds
config.yaml:528   hard_gates
config.yaml:558   weights
config.yaml:588   active_lanes
config.yaml:615   lanes — per-lane gates, thresholds, moat_critical_checks
```

Reporting and tools:

```
prospector/report.py:105          gate_fired or "min_composite" — the relabelling trap
prospector/diagnostics.py         calibration_alarms, run_calibration
scripts/ops_status.py             estate state
scripts/store_audit.py            store integrity
tools/experiments/e11_confidence_floor.py   the replay harness
```

Sibling personas: [machine-learning-engineer.md](machine-learning-engineer.md) for why a confidence is what it is and which brain ruled; [data-engineer.md](data-engineer.md) for how the store is written and locked; [finance.md](finance.md) for spend; [ops.md](ops.md) and [sre-on-call.md](sre-on-call.md) for the daemon; [product-manager.md](product-manager.md) for what the pass rate is supposed to be. Estate map: [../ESTATE_MAP.md](../ESTATE_MAP.md).

**Last measured: 2026-08-18.** Every count in this document ages. Re-run §9 before quoting any of it.
