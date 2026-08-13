# Engine audit + commercial-viability story backlog — 2026-08-13

**Tree audited:** merge commit `79aa357` (`fix/storefront-header-logo-filter-jump` merged up to `origin/main c556750`), living in the worktree `/Users/chidionyema/Documents/code/prospector-latest`.
**Corpus measured:** 1,925 scored dossiers in `store/dossiers/`, 9,746 individual checks.
**Supersedes nothing.** `docs/ENGINE_AUDIT_2026-08-10.md` (22 findings, 20 closed) stands; this document goes past it and marks its two remaining open items.

Provenance marks used throughout: **✓** = re-verified on disk in `79aa357` during this session; **○** = reported by a reconciliation agent against `79aa357`, not re-read by hand. Numbers with no mark are derived by the aggregation scripts run this session over `store/`.

> ## ⚠ CORRECTION — 2026-08-13, later the same day
>
> **The economics in this document are computed over all-time dossiers and misstate the engine as it
> runs today.** Re-derived from `store/scheduler/batch_diagnostics.jsonl`, 50 batches
> 2026-07-22 → 2026-08-13: **447 vetted → 38 PASS = 8.5%** (not ~zero), **$6.4717 total = $0.0145 per
> vetted candidate** (not $0.051), **unverifiable median 43.1%** (not 66%). Cost is bimodal — 22 of the
> 50 batches recorded **$0.00** because `claude_cli` carried them inside the subscription. The 4-candidate
> batch this audit was sized against is the most expensive, highest-provisional outlier in the set.
>
> The *defects* below stand — they were read at `file:line`. What changes is their **sizing and priority**,
> and it invalidates the premise under any scorer-replacement proposal.
> **Read `docs/ENGINE_WAR_PLAN_2026-08-13.md` first**; it carries the corrected baseline, the adjudicated
> rulings from the live 2026 research round, and the order of attack.

---

## 1. The verdict

The engine is not failing to find ideas. It is failing to **evidence** them, and then scoring that failure as if it were a judgement of quality.

1. **Two thirds of every check the engine has ever run came back `unverifiable`** — 6,426 of 9,746. Retrieval is returning pages; extraction is not turning them into cited support.
2. **The confidence number is uninformative.** Corpus-wide median confidence is **0.580 for `supported` (n=2,683) and 0.580 for `unverifiable` (n=6,426)** — identical. The formula that produces it (`prospector/verify.py:70-90` ✓) scores citation fraction, source diversity and keyword overlap, and has **no term for whether the check actually found support**. A well-cited "I could not tell" scores like a well-cited "yes".
3. **Silence is scored as zero, and zero is scored as rejection.** `min_composite` is the single biggest kill gate at **726 of 1,925 decisions**. **254 of those 726 (35.0%) scored exactly 0.00**, and those dossiers average **6.0 unverifiable checks out of 6.2** (`prospector/score.py:19-22` ✓ — "Missing axes count as 0"). A third of the engine's largest kill gate is the engine killing candidates for its own retrieval failure, in a dossier that reads as a reasoned rejection.
4. **k=100 is not a money problem.** At the measured $0.051/candidate, 100 candidates/day is ~$5.10 against the $20/day cap. The ceilings are `claude_concurrency: 4` (`config.yaml:214` ✓), `vet_workers: 3` (`config.yaml:218` ✓), **zero `asyncio` anywhere in `prospector/`** ✓ (concurrency is `ThreadPoolExecutor` at `run.py:883` and `run.py:920` ✓), and a 164 MB `store/prospector.jsonl` ✓ that takes 108s to evaluate.
5. **The reliability rail is off.** `com.prospector.watchdog` shows `-` in `launchctl list` ✓ (not running), and nothing bounds tick duration — the daemon sat ~47h inside one tick and recovered on its own, cause unknown.

The commercial consequence: 73 passes exist in 1,925 scored dossiers. The fixes that move that number most are **free** — they are extraction, scoring and configuration defects, not model spend.

---

## 2. The chain that produces zero passes

Each link is measured, not inferred.

| Link | Measurement | Where |
|---|---|---|
| Checks come back unverifiable | 66% of 9,746 checks | corpus aggregate |
| Worst-hit checks | `payer_solvency` **77.8%** unverifiable, `legality` 73.0%, `incumbency` 68.1%, `distribution` 67.7% | corpus aggregate |
| The targeted fix for two of those is switched off | `hybrid_entity_checks: []` — the config's own comment names the experiment arm as `[payer_solvency, distribution]` | `config.yaml:171-173` ✓ |
| Unverifiable axes score 0 | "Missing axes count as 0" in the weighted sum | `prospector/score.py:19-22` ✓ |
| Zero composite trips the biggest kill gate | 254 zero-composite kills of 726 `min_composite` kills | corpus aggregate |
| Survivors cluster just under the bar | nonzero composites: median **2.05**, max 3.55; **174 killed in the band [2.00, 2.50)** | corpus aggregate |
| The bar the survivors miss | `min_composite_to_pass: 2.5` | `config.yaml:294` ✓ |

**Per-lane, against each lane's own live bar:**

| Lane | Live bar | What the config's comments say the bar should be | Nonzero-composite dossiers | Clear the live bar |
|---|---|---|---|---|
| `side_hustle` | **2.5** (`config.yaml:430` ✓) | 2.0 (asserted at `config.yaml:496` ✓) | 79 | 19 (24%) — at 2.0 it would be 43 (54%) |
| `smb` | 2.6 (`config.yaml:496` ✓) | 2.6 | 56 | 13 |
| `growth` | 2.9 (`config.yaml:547` ✓) | 2.9 | 105 | 45 at ≥2.5, 14 at ≥2.9 |
| `venture` | **2.5** (`config.yaml:387` ✓) | 3.2 (asserted at `config.yaml:547` ✓) | 28 | 8 |

**The lane ladder contradicts itself.** `smb`'s comment describes `side_hustle` as 2.0 while `side_hustle` is set to 2.5; `growth`'s comment describes `venture` as 3.2 while `venture` is set to 2.5. As live values stand, **venture is the joint-easiest lane and side_hustle is no easier than venture** — the inverse of the design the same file documents. This needs a founder decision, not an engineering fix (Story S6), and it should be taken **after** S1–S5, not before: raising pass counts by moving a bar is the failure mode the founder already ruled out ("improve generation quality, not kill rate"). S1–S5 raise pass counts by making the evidence real.

---

## 3. Audit — findings confirmed against `79aa357`

24 distinct claims from the deep audit were reconciled against the merged tree. **19 confirmed, 2 already fixed by the merge, 2 not reproduced, 1 needs a live run.** Two agents did the reconciliation; the High-severity items were re-read by hand.

### High

| ID | Finding | Evidence | Fix |
|---|---|---|---|
| **A1** | Scoring has no anti-silence guard: unverifiable-dominated candidates get composite 0.0 and a permanent KILL that reads as a scored rejection | `score.py:19-22` ✓; 254/726 zero-composite kills | Exclude ungrounded axes from the denominator, or route to DEFER |
| **A2** | Confidence formula has no verdict-polarity term, so abstention scores like support | `verify.py:70-90` ✓; corpus medians 0.580 vs 0.580 | Add a polarity term; re-derive the two medians as the acceptance test |
| **A3** | Ambition-lane bars inverted relative to the config's own comments | `config.yaml:387, 430, 496, 547` ✓ | Founder decision (S6) |
| **A4** | DDG provider uses the SERP snippet only — no full-page fetch, unlike Exa | `retrieval.py:746` vs `retrieval.py:531` ○ | Add GET + extract to the DDG provider |
| **A5** | `numeric_citation` is shadow-mode-only forever; no acting variant exists | `numeric_citation.py:219`, `config.yaml:1391` ○ | Build the demote-on-threshold action variant |
| **A6** | Spend ledger is written with stdlib `logging.FileHandler`, not the repo's own concurrency-safe primitive | `telemetry.py:100` ✓ vs `jsonl_atomic.py:174` ✓ | Route through `append_jsonl`. The audit's own 8-process stress test did **not** reproduce corruption — this is a design inconsistency on the money rail, not a demonstrated loss |
| **A7** | The drain halts entirely when `claude_cli` alone is dead (`trusted_only=True`), which already cost a 21.7h stall | `health.py:284`, `run_scheduled.py:503-504` ○ | None — this is the documented, founder-accepted 2026-08-08 tradeoff. Re-flagged, not re-opened |

### Medium

| ID | Finding | Evidence |
|---|---|---|
| A8 | E1 entity-templated queries disabled — built precisely for the two worst-performing checks | `config.yaml:173` ✓, `verify.py:561-562` ○ |
| A9 | Evidence passages truncated by blind char-slice; a sentence-aware clip exists but is used only on output | `verify.py:432` vs `verify.py:524` ○ |
| A10 | The discriminating local embedding is wired only to an inert shadow prescreen, never to reranking | `prescreen_prefilter.py:1-53` ○ |
| A11 | ~~Reports-page-only~~ — **corrected below, this is on the hot generation path (B-C2)** | `report.py:610`, `adaptive.py:94` ✓ |
| A12 | `provisional` column is unindexed → full table scan every tick | `store.py:45-54` ○ |
| A13 | `kill_decay.py`'s diversity-floor mechanism is imported nowhere in production | `rg kill_decay prospector/` → docstring only ○ |
| A14 | Exhausted-family denylist clusters on title/one-liner only, missing structural repetition | `denylist.py:35-42` ○ |
| A15 | No retrieval-quality golden set or CI receipt exists; `golden.py` checks decision-match only | `golden.py:96-131` ○ |
| A16 | `claude_concurrency: 4` contradicts the config's own "N=8 knee" comment | `config.yaml:214` ✓ |

### Low

`store.save()` globs the whole dossier dir per write (`store.py:192` ○) · the retrieval DiskCache never evicts, TTL only marks stale (`retrieval.py:1258` ○) · `PAUSE` is not checked on manual `run.py` CLI paths ○.

### Already fixed — do not re-open

- The `min_composite`/`source_or_die` early-exit now short-circuits the check loop (`verify.py:911-925`, via `pass_ceiling.py`) ○.
- `guard.evaluate()`'s 108s full-ledger scan is incremental since 2026-08-10 (`guard.py:211-302`) ○. **The 108s number still applies to the state probe and the Reports page**, which take a different path (A11).

### Not reproduced

- The untagged-`ambition_tier` DEFAULT branch (`run.py:862-871`) is unreachable while `active_lanes` is non-empty ○. The corpus agrees it is *mostly* historical — untagged share ran 77% (Jun) → 88% (Jul) → **27% (Aug)** — but 27% is not zero, so something is still producing untagged rows and that residue is worth one hour of tracing.
- `dedup_dropped=0` is by design: `catalogue_titles()` deliberately excludes the kill graveyard (`store.py:238-252` ○).

### Still open from the 2026-08-10 audit

- **#14 MEDIUM** — `MOAT_PRIMARY` provisional-stamping single-operator gap (`operator.py:1093-1100` ✓).
- **#20 LOW** — `pricing.py`'s no-ladder fallback is a hardcoded literal: `int(listing.get("price_pence", 4999))` (`pricing.py:126` ✓). Money rail.

---

## 3b. Second reconciliation pass — 15 further findings

A second pass over the remaining audit reports found 15 confirmed defects that the first pass did not cover, plus one correction to a claim in §3. The four that change what to do first were re-read by hand.

### High — new

**B-C2 · The full 164 MB ledger scan runs on every scheduled generation tick, not on a dashboard button.** ✓
This corrects A11 above, which understated it as a Reports-page cost. The chain is unconditional: `run_scheduled.py:824` → `run.py:1121-1122` (`calibration_alarms`, called with no guard) → `diagnostics.py:338-339` → `adaptive.py:94`, which is a bare `jsonl_path.read_text().splitlines()`. The daemon pays a full-file read of a 164 MB file every time it generates. **This moves S10 from housekeeping to a k=100 blocker** — at k=100 the daemon ticks more often against a ledger that grows faster.

**B-B4 · The `PAUSE` kill switch is not checked by `run.py` at all.** ✓
`rg -c PAUSE prospector/run.py` → **0**. `PAUSE` lives only in `scheduler/guard.py:66`, imported solely by the daemon (`run_scheduled.py:41`). Direct CLI invocations of `run.py` use a separate `SpendGuard` (`spend.py:11`) with no filesystem awareness, so **they bypass the kill switch entirely**. The project's own rule calls `PAUSE` "the liability rail… because a rail with exceptions is not a rail" — this is that exception. The first pass rated this Low; it is not Low.

### Medium — new, and one is a one-word fix

**B-D4 · The denylist's gate filter matches a string the engine never writes.** ✓
`denylist.py:33` — `FAMILY_GATES = frozenset({"value_durability", "incumbency", "adversarial"})`. The value actually written is `"adversarial_decisive"` (`kill_filter.py:62`, `verify.py:992`). The string never matches, so **every adversarial-driven kill is silently excluded from family clustering — 142 kills in the corpus, the 4th-largest gate.** One word.

**B-B6 · `CrossProcessSemaphore` silently degrades to a per-process semaphore.** When `_slot_root()` fails — permissions, disk, sandboxed HOME — `cli_governor.py:139` falls back to `threading.Semaphore` and **logs nothing**. The machine-wide concurrency guarantee disappears with no trace. The one warning in that file is on an unrelated env-var path.

**B-D8 · Dedup's comparison pool is PASS-only.** `store.py:248-249` — `WHERE decision = ?` bound to `Decision.PASS.value`. The first pass called this by-design and it is; the consequence is still that dedup compares each new candidate against 73 passes and never against the ~1,850 killed ones, which is why `dedup_dropped` sits at zero.

**B-B1 · The soft early-exit branch is dead in every real config.** `pass_ceiling.py:90-92` triggers below a 5.0 ceiling, but every live `min_composite_to_pass` is 2.5–3.8 (`config.yaml:387, 430, 496, 547, 1126, 1139, 1154`). Not "structurally impossible" as first reported — dead as configured. Either redesign mid-run composite estimation or delete the branch.

**B-D5 · No near-miss re-review exists.** Nothing routes a `min_composite` kill that lands just under the bar to a second opinion. Given 174 kills in the band [2.00, 2.50), this is the cheapest possible source of additional passes that does not touch a bar.

### One correction to §3

The claim "no retrieval-quality or groundedness metric exists anywhere" is **too strong**. `tools/experiments/e15_hhem_groundedness.py` and `e17_hhem_moat_agreement.py` exist with receipts. The accurate claim, and what S13 must build, is that **no groundedness gate is wired into CI or any recurring check** — the measurement exists as a one-off experiment, not as a standing receipt.

### Also confirmed, lower priority

`numeric_citation` has no enforcement path and this is an explicitly pending founder policy decision, not an oversight (`config.yaml:1390-1391`) · the embedding prescreen prefilter is shadow-mode by design, lexical is the only backend that drops (`prescreen_prefilter.py:536-547`) · passage truncation is a bare mid-word slice at **13 more sites** across `retrieval.py`, not just `verify.py:432` · `report.py` implements the full-ledger scan **twice** (`:154` and `:583`), so `prospector report --full` pays both plus a third via `calibration_alarms` · the `provisional` full-table scan fires via the unconditional `_resume_per_tick` drain (`run_scheduled.py:92, 807`), not via the disabled backlog brake as first attributed · the SessionStart state probe carries a hardcoded 20 MB ledger gate and prints a canned "108s" message rather than measuring (dormant only because the probe reads a different, small file).

**Second-pass totals: confirmed 15 · not reproduced 1 · already-covered duplicates 13.**

---

## 4. k=100 with parallel runs, at flat AI cost

**The cost case is already closed.** $0.051/candidate × 100 = **$5.10/day against a $20/day cap**. Nothing in this section needs new spend; some of it removes spend.

The real ceilings, in order of what binds first:

1. **Process spawn.** Every LLM call spawns a fresh `claude` CLI subprocess — 0.42s overhead per call (measured, n=5) plus the already-documented 8.6× cold-cache write tax. `claude -p --input-format stream-json` supports a persistent worker pool today.
2. **Concurrency caps.** `vet_workers: 3`, `claude_concurrency: 4` ✓, enforced machine-wide by the flock governor in `cli_governor.py` ○ — so sharding across processes adds nothing until the slot count itself rises. The config's own comment already prescribes the A/B that would justify raising it.
3. **No asyncio.** Zero occurrences in `prospector/` ✓. Not a defect — the bottleneck is subprocess spawn and provider throttling, not thread scheduling — which is precisely why an asyncio rewrite is **not** in the backlog.
4. **Checkpoint granularity.** Checkpointing is per candidate, so a crash on check 6 of 7 re-pays checks 1–5.
5. **Ledger reads.** 164 MB JSONL ✓, 108s to evaluate — already over the state probe's 30s budget, and it grows super-linearly with k.
6. **Circuit breaker shape.** A 3-consecutive-failure trip will false-trip on the simultaneous 429 bursts that k=100 makes normal; a windowed K-of-M rate trip is the standard answer.

---

## 5. If we built it from scratch in 2026

Six independent research agents, two of them deliberately given opposite priors (evolution vs revolution). **Convergence between opposite priors is the funding signal**, and it landed on one thing.

**Converged (2+ independent agents, same fix for the same symptom):**

- **A local cross-encoder rerank before the 600-char truncation.** BGE-reranker-v2-m3 (0.6B, CPU-viable). Anthropic's own measurement: reranking cuts top-20 retrieval failure from 5.7% to 1.9% — a 67% relative reduction ([Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval), 2024-09-19). This sits directly upstream of the 66% unverifiable rate and costs no AI spend.
- **Do not widen the context to fix unverifiability.** Two agents converged from opposite directions that shorter, better-selected context is a free win rather than a tradeoff ([Context Rot](https://research.trychroma.com/context-rot), 2025-07-14; Lost in the Middle, TACL 2024). This kills the intuitive fix ("retrieve more") and is why A4/A9/S4 are about *selection*, not volume.

**Strongest single cost-removal opportunity:** a local NLI model as the first-pass verdict engine, with the LLM escalating only near-margin cases. MiniCheck (770M) matches GPT-4-level fact-checking at ~400× lower cost on exactly this input shape — claim + grounding document → verdict ([arXiv:2404.10774](https://arxiv.org/abs/2404.10774), EMNLP 2024). It does not touch the doctrine that only `MOAT_PRIMARY` may finalise a verdict; it changes what the trusted brain is *asked*.

**Structural warning worth internalising:** 43 experts executed randomly-assigned research ideas; AI-generated ideas' scores dropped significantly more than human ideas' after execution, with a ranking flip ([The Ideation-Execution Gap](https://arxiv.org/abs/2506.20803), 2025-06-25). That is direct evidence that an LLM's pre-execution rating of an idea — which is what the composite score is — decouples from realised value. It argues for grounding weight over rubric weight, and against ever tuning the composite to produce more passes.

**Explicitly rejected by the research, all for the same reason (they break flat cost or subscription-only billing):** orchestrator-worker multi-agent research (measured ~15× tokens), the Message Batches API (real 50% discount, but needs raw API-key billing), sentence-level claim decomposition (measured −5.3 to −8.9 accuracy points at this granularity), and a full asyncio/Temporal/DBOS rewrite.

**Disputed, unresolved:** whether to *replace* the paid LLM query-gen call with the free deterministic `_keywords()` extractor (one agent: the single lever that funds k=100 out of the verification budget) or *keep and improve its prompt* for multi-perspective diversity (another agent: lowest-risk change, zero cost delta). Both cannot be primary at the same call site. Resolvable by A/B behind the golden set from S13 — which is why S13 is not optional.

---

## 6. The story backlog

Ranked by (commercial impact) × (cheapness). Cost class: **FREE** = no additional AI spend (local CPU/GPU counts as free); **NEUTRAL** = same call count, different content; **PAID** = must name what pays for it. Every story carries an acceptance test that is a command or a number, not a judgement.

### Tier 1 — free, and they move the pass rate directly

**S1 · Stop scoring silence as zero.** `score.py:19-22`. Exclude ungrounded axes from the composite denominator, or route an unverifiable-dominated candidate to DEFER instead of KILL.
*Size S · FREE ·* **Accept:** re-scoring the 254 zero-composite dossiers produces zero `min_composite` kills at composite 0.00; no candidate is killed on a gate it was never evidenced against.

**S2 · Make confidence mean something.** `verify.py:70-90`. Add a verdict-polarity term so an abstention cannot outscore a support.
*Size S · FREE ·* **Accept:** corpus median confidence for `supported` exceeds `unverifiable` by a stated margin; today both are exactly 0.580.

**S3 · Switch on the entity-templated queries already built for the two worst checks.** `config.yaml:173` → `[payer_solvency, distribution]`.
*Size S (flag flip) · FREE ·* **Accept:** `payer_solvency` unverifiable rate falls from **77.8%** and `distribution` from **67.7%** over the next 200 checks; kill-gate mix shifts off `moat_ungrounded` (387 kills today).

**S4 · Local cross-encoder rerank before truncation.** Rank retrieved passages locally, then truncate to the same budget. Do **not** widen the context.
*Size M · FREE (local CPU) ·* **Accept:** unverifiable share of checks falls below 50% (from 66%) on the S13 golden set, at unchanged token spend.

**S5 · Fetch the page, not the snippet.** `retrieval.py:746` — give DDG the GET+extract step Exa already has.
*Size S/M · FREE ·* **Accept:** mean passage length and cited-source diversity from DDG-sourced checks reach parity with Exa-sourced ones.

**S6 · Founder decision: fix the lane ladder.** The values and the comments disagree (§2). Either correct `venture` to 3.2 and `side_hustle` to 2.0, or correct the comments.
*Size S · FREE · Blocked on the founder ·* **Accept:** every lane bar matches every comment that names it. **Do this after S1–S5** so the pass rate moves on evidence quality first and the bar change is measured against a clean baseline.

### Tier 2 — free, and they unlock k=100

**S7 · Persistent CLI worker pool.** Replace per-call subprocess spawn with `claude -p --input-format stream-json` workers.
*Size M · FREE (removes spend) ·* **Accept:** wall-clock per candidate drops by ≥0.42s × calls-per-candidate; cache-write tokens fall measurably.

**S8 · Per-check checkpointing to sqlite.** A crash re-pays one check, not one candidate.
*Size S/M · FREE ·* **Accept:** kill the daemon mid-candidate; `vet --resume` restarts at the interrupted check.

**S9 · Bound the tick and restore the watchdog.** `_write_heartbeat` (`run_scheduled.py:147`) only stamps at phase transitions; nothing caps tick duration; `com.prospector.watchdog` is `-` in `launchctl list` ✓. This is what let a 47h hang pass unnoticed.
*Size S · FREE ·* **Accept:** a tick exceeding a configured ceiling self-aborts and logs; `launchctl list` shows a live PID for the watchdog.

**S10 · Incremental ledger aggregates.** Extend `guard.py`'s 2026-08-10 incremental pattern to `report.py:610` and `adaptive.py:94`.
*Size M · FREE ·* **Accept:** the state probe's live spend read completes inside its 30s budget against the 164 MB ledger.

**S11 · Raise the concurrency ceiling on evidence.** Run the A/B the config's own comment at `config.yaml:214` prescribes, then set `claude_concurrency` / `vet_workers` to the measured knee. Keep the flock governor.
*Size S · FREE ·* **Accept:** a published throughput curve; k=100 completes within one tick interval.

**S12 · Windowed circuit breaker.** K-of-M rate trip instead of 3-consecutive.
*Size S · FREE ·* **Accept:** a simulated burst of simultaneous 429s does not trip the breaker; a sustained outage still does.

### Tier 3 — the structural bets

**S13 · A retrieval-quality golden set and a recurring receipt.** Nothing today measures retrieval quality; `golden.py:96-131` checks decision-match only. **Every story above claims a number that this story is what proves.** It also settles the query-gen dispute in §5.
*Size M · FREE ·* **Accept:** one command prints unverifiable rate, citation diversity and confidence separation, on a fixed case set, before/after any change.

**S14 · Local NLI first-pass verdicts, LLM escalates near-margin.** The largest cost-removal opportunity found (§5). Does not change who may finalise a verdict.
*Size L · FREE (local) ·* **Accept:** agreement with the trusted brain on a held-out set at a stated threshold; verdict-side token spend falls, with escalation rate reported.

**S15 · Money-rail and correctness debt.** Route the spend ledger through `jsonl_atomic.append_jsonl` (`telemetry.py:100` ✓); replace `pricing.py:126`'s hardcoded `4999` fallback (2026-08-10 audit #20); close #14's `MOAT_PRIMARY` single-operator gap; index the `provisional` column (`store.py:45-54`).
*Size S each · FREE ·* **Accept:** no money-rail write bypasses the atomic primitive; no price literal outside `config.yaml`.

**S16 · Housekeeping with a real cost.** Sentence-aware passage clipping (`verify.py:432`) · DiskCache eviction (`retrieval.py:1258`) · either wire in or delete `kill_decay.py` and its false docstring claim · extend the denylist beyond title clustering · trace the residual 27% untagged `ambition_tier`.
*Size S each · FREE.*

---

### Amendments from the second reconciliation pass

**S17 · Make the kill switch actually a kill switch.** `run.py`'s CLI entrypoints must call the same guard the daemon does before mutating state — `PAUSE` currently stops the daemon and nothing else.
*Size S · FREE ·* **Accept:** with `store/scheduler/PAUSE` present, every state-mutating `run.py` subcommand refuses, not just the scheduled tick.

**S18 · Fix the denylist's dead gate string.** `denylist.py:33` → `"adversarial_decisive"`.
*Size XS · FREE ·* **Accept:** family clustering sees the 142 adversarial kills it currently drops; `exhausted_families` reflects them.

**S19 · Make the governor's degrade audible.** Log and audit the first time `cli_governor` falls back to a per-process semaphore.
*Size XS · FREE ·* **Accept:** a run with an unwritable slot root emits exactly one warning and one audit row.

**S20 · Near-miss second opinion.** Route `min_composite` kills within a configured margin of the bar to one re-review. 174 kills sit in [2.00, 2.50).
*Size M · NEUTRAL — needs a named budget ·* **Accept:** re-review rate and its conversion to PASS are both reported; the margin is a config value.

**S10 is re-ranked into Tier 2's top slot** — the full-ledger scan is on the generation hot path (`run.py:1121-1122` → `adaptive.py:94`), not the Reports page, so it binds k=100 directly.

**S13's scope is corrected** — build the *standing receipt*, not the measurement. `tools/experiments/e15_hhem_groundedness.py` already measures groundedness; nothing runs it on a schedule.

---

## 7. What this does not claim

- **A6** (money-rail ledger writer) is a design inconsistency; the audit's own 8-process stress test did not reproduce corruption. It is worth fixing because the repo already owns the safe primitive, not because loss was observed.
- **A7** (drain halts on trusted-only exhaustion) is the founder's accepted 2026-08-08 tradeoff, re-flagged for visibility, not re-opened.
- The 47h daemon hang **recovered on its own and its cause is unknown**. S9 bounds the blast radius; it does not diagnose the hang.
- Every unverified-by-hand claim carries an **○** and names the file to check. Nothing in §6's acceptance tests has been run yet — they are the contract for the work, not evidence that the work is done.
