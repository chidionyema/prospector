# Engine war plan — order of attack, gates, and rules of engagement

**Supersedes the baseline in** `docs/ENGINE_AUDIT_AND_STORIES_2026-08-13.md`. That audit's headline
economics were computed over all-time dossiers and are wrong for the engine as it runs today; §1 below
carries the corrected numbers, all re-derived on disk this session.
**Inputs:** the 22-finding audit (20 closed), the 34-finding reconciliation, and the live 2026 research
round — 9 agents, 6 areas, 66 sources, an evolution design, a revolution design, and an adversarial
adjudication between them. Research harvested to
`…/scratchpad/harvest/live-research-*.{json,md}` — **durable; do not re-run.**
**Constraint that shapes everything:** no increase in AI spend. Local CPU is free.

---

## 1. The correction that reframes the attack

I measured this myself from `store/scheduler/batch_diagnostics.jsonl`, 50 batches,
2026-07-22T09:08 → 2026-08-13T06:23:

| | Audit said | **Verified today** |
|---|---|---|
| PASS rate | ~zero | **38 / 447 vetted = 8.5%** |
| Cost per vetted candidate | $0.051 | **$6.4717 / 447 = $0.0145** |
| Unverifiable share | 66% | **median 43.1%** (min 17.1, max 64.8) |
| Funnel | — | 481 generated → 447 vetted → 38 PASS / 386 KILL / 23 DEFER / 48 provisional (10.7%) |

**The engine is not producing nothing.** The batch the audit was sized against — 4 candidates, 0 passes,
$0.2043 — is the most expensive, highest-provisional outlier in the set. **Cost is bimodal: 22 of 50
batches recorded $0.00** because `claude_cli` carried them inside the subscription; the expensive days
are the days it was walled. Averaging that into a per-candidate rate is what makes a cost plan look
funded when it isn't.

**Three consequences.**
1. k=100 costs **~$1.45 per wave** against a $20/day cap. The money question is closed twice over.
   Everything in Wave 3 is wall-clock, and must never be sequenced ahead of something that moves quality.
2. The right cost model is **P(walled) × walled-day cost**, not a mean. Every provider-caching and
   chain-ordering lever pays only in that tail.
3. "The ruler is broken" and "the ideas are bad" are both **under-evidenced**. The engine reaches
   composites of 3.0 and passes 8.5% of what it vets. Do not fund a scorer replacement on the old premise.

---

## 2. The three rules

1. **Nothing ships without a receipt** — a number before and after, from the same command. A wave that
   lands without its receipt is unmeasured, not done.
2. **Change one causal layer at a time.** Retrieval, confidence and the pass bar all move the pass rate.
   Move them together and nothing is attributable.
3. **Safety before speed.** We are about to run many experimental batches against a live daemon that
   spends money and writes tracked state.

---

## Wave 0 — Settle the argument, then make the ground safe

The two clean-sheet designs disagree on **one** thing: order of operations. Evolution says the pipeline
shape is right and the fixes sit downstream of retrieval. Revolution says you must be able to rank for
free *before* paying, or k=100 never pays for itself. Every revolution saving rests on one unproven
proposition — **that something computable for free predicts the paid outcome.**

**W0.1 — The decisive experiment. Run this before funding anything.**
Take the 447 vetted candidates and their stored dossiers, which already carry ground truth
(38 PASS / 386 KILL / 23 DEFER). For each, compute only features available *before* any paid check:
local `nomic-embed-text` embedding of the one-liner, k-NN distance to historical PASS/KILL centroids,
dedup similarity to the live catalogue, lane, market, archetype, and the verbalized-sampling typicality
score already being generated and thrown away. Fit on batches before 2026-08-05, test after, report AUC.

- **AUC ≈ 0.5** → nothing free predicts the outcome. Revolution loses its funding mechanism; spend the
  quarter on retrieval selection (Waves 1–2) and stop there.
- **AUC > ~0.75** → free pre-ranking genuinely concentrates the paid budget on survivors, and Wave 3's
  admission ordering becomes a headline item rather than plumbing.
- Either way it funds **ORDERING, never KILLING** — an embedding is not a citation, and a kill without
  a retrievable source violates verdict-from-retrieval-only.

Zero tokens, zero web calls, an afternoon of local CPU, against the largest labelled evidence set the
project owns. Both designs proposed spending money to test hypotheses about a batch of four while
ignoring 447 labelled outcomes on disk.

**W0.2 — The standing receipt.** One command printing: unverifiable rate (per check and overall),
confidence separation by verdict polarity, composite distribution, PASS rate, and $/vetted over a
stated batch window. `tools/experiments/e15_hhem_groundedness.py` already measures groundedness —
extend it, do not rebuild it. Commit today's output as the baseline.

**W0.3 — Fix the cost instrument before trusting any cost claim.** In the last batch,
`input 420,082 + output 308,297 = 728,379` but `total` reads **1,990,168**. `claude_cli` reports
`input: 70`. Every phase-level split and every per-stage number in both designs is computed on a field
that is not a billed dimension. Add a provider dimension to the phase counters and reconcile.

**W0.4 — Land the merge.** Main checkout is at `d4ad901`; `79aa357` is a fast-forward living only in
`../prospector-latest`. Everything branches from it or repeats the stale-tree failure this audit exists
to correct. 83 dirty paths — **never `git add -A`**.

**W0.5 — The stop button.** `PAUSE` for `run.py`'s CLI entrypoints (`rg -c PAUSE prospector/run.py`
→ **0** today), a bound on tick duration, heartbeat refresh inside long phases, watchdog running.
A 47h silent hang already happened and is still undiagnosed; during a rebuild we cannot tell a hang
from a slow experiment.

**Gate:** AUC reported with its train/test split · receipt committed as baseline · token fields
reconcile · `PAUSE` refuses a manual mutation · watchdog shows a live PID.

### Wave 0 status ledger — updated 2026-08-13, and it is the only place Wave 0 status lives

Prose elsewhere saying an item is done is a lead, not state; this table is the record and every row
names the artefact that proves it. **Wave 0 is CLOSED.**

| Item | Status | The receipt |
|---|---|---|
| **W0.1** | **CLOSED, negative** | `tools/experiments/w0_free_prescreen_auc/` — README + `auc.out` + `dense.out` and the six scripts that produced them. |
| **W0.2** | **DONE, baseline committed** | `tools/experiments/w02_standing_receipt.py`, output in `w02_standing_receipt_receipts.json`. |
| **W0.3** | **DONE** | token ledger reconciles; `tests/unit/test_token_ledger_reconciles.py`, commit `64495ed`. |
| **W0.4** | **DONE** | merge landed, `3917ea4`. |
| **W0.5** | **DONE** | `PAUSE` on the CLI (`tests/scheduler/test_pause_blocks_manual_cli.py`, `64495ed`); tick bound already shipped as `_TICK_HARD_DEADLINE_S = 10800`; heartbeat refresh inside long phases + atomic write (`tests/scheduler/test_working_phases_keep_beating.py`). |

**W0.1 answered the plan's own question with the plan's own decision rule, and the answer is
`AUC ≈ 0.5`: revolution loses its funding mechanism.** On the regime-restricted temporal split the
lexical arm reaches **0.502** and every `nomic-embed-text` variant lands **0.375–0.411** — the dense
arm being the feature this section named, so it was run rather than ruled on by proxy. The
unrestricted split's 0.61–0.66 must not be quoted: June 2026 contributed 724 candidates and zero
passes, so a model fitted across that boundary scores by learning "June-era phrasing ⇒ kill". The
stratified 5-fold figure of **0.770 ± 0.038** *clears* the 0.75 headline bar above and is worthless
for the same reason, one step worse — shuffling folds across the June boundary puts the regime label
in train and test. Full argument and the surviving free lever (US 14.2% [8.8, 22.0] vs UK 4.6%
[3.4, 6.2] within 2026-08) in that directory's README.

**W0.2's first baseline already pays for itself: it independently confirms the Wave 1 "Confidence
polarity" diagnosis below, and shows it is worse than stated.** Over 2026-08-07..13, 577 dossiers,
2704 checks: mean confidence is **supported 0.577 / refuted 0.564 / unverifiable 0.607** — a ruled-
minus-unverifiable gap of **−0.033**. The plan says confidence has "no polarity branch"; the
measurement says the field is mildly *inverted*, so the engine is at its most confident precisely
where it ruled on nothing. Also from that run: unverifiable **63.7%** of checks (worst
`payer_solvency` 78.8%, best `currency` 44.6%) against only 19 `retrieval_failed` and 19 `degraded`,
so this is the web lacking passages and not our retrieval breaking; PASS rate **18/577 = 3.1%**
[2.0, 4.9]; composite mean 2.062 against a bar of 2.5 with 26/141 scored dossiers at or above it;
**$/vetted $0.0088 metered, $2.82 subscription-equivalent.**

**DEVIATION ON W0.2, FLAGGED FOR OVERRULE.** This section says "extend `e15_hhem_groundedness.py`,
do not rebuild it", and W0.2 shipped as a new module instead. The instruction's force — do not write
a second corpus reader — is obeyed exactly: every dossier is read through `tools/experiments/_corpus.py`,
the same accessors E15 uses, and the spend leg goes through `SchedulerGuard.spend_by_day()` rather
than any new parse of `store/prospector.jsonl`. What is not reused is E15's body, because E15 loads a
neural entailment model and samples a few hundred ruled checks: folding a whole-corpus dashboard into
it would make printing a PASS rate depend on a model download, and would overwrite E15's receipts,
which are a measurement of record.

---

## Wave 1 — Free levers that need no experiment

Zero tokens, all reversible, no doctrine surface. Six different files, so they run concurrently.

| Item | Where | The edit | Acceptance |
|---|---|---|---|
| **Confidence polarity** | `verify.py:70-90` | Zero the diversity and relevance terms on an UNVERIFIABLE verdict. Today confidence is citation-fraction 0.30 + diversity 0.40 + overlap 0.30 with **no polarity branch**, so it rewards evidence *volume*, never decisiveness. | Supported median exceeds unverifiable by a stated margin. Validate offline over stored dossiers — no model calls. **Ships FIRST: the adaptive hop in Wave 2 triggers on this number.** |
| **Anti-silence scoring** | `score.py:19-22` | Ungrounded axes leave the denominator, or the candidate routes to DEFER. Never score silence as 0. | No `min_composite` kill at composite 0.00. Prove on a **shadow** re-score — never mutate a stored dossier. |
| **Typicality → selection** | `config.yaml:868-873` | The comment says outright: *"the self-reported typicality is observability only; nothing is filtered, reordered or down-weighted by it."* `atypical_threshold: 0.3` and `min_atypical_fraction: 0.4` are already there and inert. Wire them into selection. | The only change anywhere that converts **already-purchased output tokens** into product at zero marginal cost. |
| **Generation blind to the rubric** | generation prompts | Generation is never shown the six scoring axes. | Goodhart: the scoreboard is not the target. Also protects every later experiment from being graded by an instrument the generator writes toward. |
| **Promote what is already built** | `config.yaml:1349`, `:1401` | `prescreen_prefilter.shadow_mode: true` and `coverage_sampler.enabled: false` ("inert until switched on"). Both built, tested, config-gated, reversible. | Promote on the agreement measurement the config itself demands, not on argument. |
| **Denylist string** | `denylist.py:33` | `"adversarial"` → `"adversarial_decisive"`. | 142 kills rejoin family clustering. One word. |
| **Governor logging** | `cli_governor.py:139` | One warning + one audit row on the degrade path. | An unwritable slot root produces exactly one warning. |

**Hazards:** anti-silence scoring can convert kills into DEFERs en masse and grow a backlog the drain
is **trusted-only by design** — it cannot drain on the days it grows. Cap the conversion and watch
`run.drainable()`. Both scoring and confidence changes alter verdict semantics: the Part 13B golden-set
gate must pass; a mixed-sector discrimination regression blocks ship.

---

## Wave 2 — Retrieval selection (the convergent core)

Two architects, opposite priors, same conclusion: **retrieval-empty checks are zero — pages are always
found. The defect is WHICH 600 characters reach the model.** At least 55% of the unverifiable population
is native extraction failure, not the safety rails firing (both rails force confidence to exactly 0.0;
the observed unverifiable median is well above that, so those rulings carry real citations).

1. **Widen the free tier only.** `config.yaml:153 results_per_query: 3` applies uniformly; Exa is
   metered. Raise DDG to 8–10, leave Exa and claude_cli alone, truncate to the same final budget.
   This is a *prerequisite* — without it the reranker has nothing to rank.
   **Condition: instrument DDG throttle responses first.** At k=100 this is 1,280+ queries per wave
   against a provider with a documented split-brain incident, and the fallback from a throttled DDG is
   *metered Exa*. That third rail is claimed to fall in both designs and priced in neither.
2. **Local cross-encoder rerank + MMR** between `search.search()` and the truncation, holding the final
   passage budget identical. Zero tokens by construction — it can only shrink the verdict prompt.
   **Ship it behind its own A/B, not behind Anthropic's 67%.** I checked the source: reranking's own
   step is 2.9%→1.9% (1.0pp), while contextual embeddings' is 5.7%→3.7% (2.0pp) — reranking is *not*
   the largest step, and the measured setting was an index Anthropic built and embedded itself, not
   third-party snippets some of which are under 200 characters. **Falsification both designs agreed on:
   a flat score distribution over short snippets means there is nothing to rank.**
3. **Sentence-aware clipping** at all 14 truncation sites. `clip_to_sentence` exists at `verify.py:524`
   and is applied to output only.
4. **Semantic index over evidence already paid for** — SQLite FTS5 + the existing `nomic-embed-text`
   embedder, RRF-fused, over `store/_cache` (~21,000 passages), consulted before the live chain.
   `rg -ln fts5 --glob '*.py'` returns nothing today. **Shadow mode first.** Both designs independently
   specified the identical fence: cache-served passages stamped in `provider_chain`, tightened TTL for
   `legality` and `payer_solvency`. That unprompted agreement is the strongest signal in the pair — it
   is how this breaks source-or-die, and they both saw it. It is a throughput lever before it is a cost one.
5. **Sufficiency-gated second hop** — `queries_per_check` 2→1 plus one conditioned follow-up fired only
   on thin evidence, under a hard per-candidate cap that preserves the kill-fast worst case.
   **Ships last in this wave and only after the confidence fix**, because the trigger *is* the confidence
   score. Re-derive its self-funding arithmetic at **unverifiable = 43%**, not the outlier batch's 33%;
   at the true median the hop fires more often and the token delta goes net-positive.

**Gate:** unverifiable median below 35% (from 43.1%) at unchanged or lower token spend, golden set green,
and each of the five items attributable on its own A/B.

---

## Wave 3 — k=100 (wall-clock only)

$1.45 per wave. Nothing here moves money, so nothing here is sequenced ahead of Waves 1–2.

1. **Kill the full-ledger scan on the hot path.** `run.py:1121-1122` calls `calibration_alarms`
   unguarded on every generation tick → `adaptive.py:94` `read_text().splitlines()` over a 164 MB
   ledger; `evaluate()` takes 108s against a 30s probe budget. Extend `guard.py`'s incremental pattern
   and keep `prospector.jsonl` append-only and immutable. **Biggest wall-clock item; grows with k.**
2. **Per-check checkpointing** keyed by `(candidate_id, check_name)`, so a crash re-pays one check.
3. **Admission ORDERING, batch-wide.** The real defect underneath revolution's strongest insight:
   `min_composite` is the modal kill gate, and it is computed only *after* every paid check has run.
   Run the whole wave's cheap deterministic gates before any candidate enters verify, then order the
   queue so likeliest survivors are researched first. Nothing is killed without cited evidence — the
   tick simply runs out of time on the least promising tail. **Funded by W0.1's AUC.**
4. **Persistent `claude -p --input-format stream-json` worker pool.** Removes 0.42s median spawn and
   the 8.6× cold-cache write tax. **Non-negotiable gate: prove cross-prompt context isolation on
   grounding calls before any verdict call touches the pool.** A leak between candidates is a doctrine
   violation, not a performance bug. Saving is wall-clock and subscription cache-writes, not dollars.
5. **Windowed K-of-M breaker** replacing `breaker_failure_threshold: 3` consecutive. The concern is
   real — claude_cli was dead-marked nine times in 70 minutes on 2026-08-06 off ~3s backpressure — but
   it is labelled HYPOTHESIS by both designs. **Build the free replay harness against those recorded
   timings; ship nothing unless the replay shows the consecutive rule tripping under an interleaved
   burst.** Honour that falsification.
6. **Index `dossiers.provisional`**, scanned every tick by the unconditional drain pass.
7. **Stable prefix ordering on MiniMax calls** — it cached **0 of 420,082** input tokens against
   claude_cli's 647,108 of 1,309,128. A 20-call probe costs under a cent. Book it honestly: this pays
   only on days claude_cli is walled. Cheap insurance for the bad day, not a steady-state saving.

**Gate:** k=100 completes inside one tick interval, with a published throughput curve. Note realised
throughput today is ~4 candidates per 50 hours and **nobody has explained that gap** — it is a
prerequisite finding, not an assumption.

---

## Wave 4 — Contested items, funded only by what Wave 0 returns

- **Local NLI (MiniCheck-class) as a router — never as a token saving.** The 770M model genuinely
  reaches GPT-4-level grounding accuracy at ~400× lower cost, but the claimed "70% of trusted calls
  removed" is internally contradictory: under the stated fence, *both* router outcomes still terminate
  in a trusted call, so the trusted-call count is unchanged and the saving is zero. Either the doctrine
  holds and the money evaporates, or a local model silently rules 70% of checks and we manufacture the
  ancestor already on disk at `store/dossiers/2102bacc6dd75cf9.kill.json` — a fully-reasoned-looking
  dossier whose every check read *"Verdict call failed; fail-safe."* **Fund it as passage selection and
  second-hop trigger. Book zero dollars.**
- **Post-hoc calibration of the scorer — not a pairwise replacement.** The central-tendency compression
  is real and documented, but the source recommends *calibration-aware evaluation and post-hoc
  calibration*, and its ablations covered few-shot exemplars and prompt modification, **not alternative
  scoring methodologies**. Calibration is cheaper, reversible, and preserves comparability with 2,012
  historical composites that a scorer swap destroys. Measure the spread offline first. Guard: nothing
  newly-passing publishes without a human read.
- **Batched generation** (8–12 ideas per call against a stable cacheable prefix). The stratification
  result is real and quoted verbatim, but it is measured across *creative* task families, not
  constrained JSON under archetype bindings and a 104-cell matrix, and the paper publishes **no** result
  on how many ideas may be drawn per call before intra-call mode collapse — which is the assumption
  carrying both cost sums. **The stable-prefix half is free and separable: ship it regardless.** Gate
  the batching on the existing `diversity_meter` distinct-k receipt and the dedup drop rate.
- **Extend `incumbent_seed` to `pain_reality` and `payer_solvency`** as ungraded generation context.
  Bounded and doctrine-safe (injected context is never a Source and can never kill). Must inherit the
  existing exclusion of `claude_cli` from generation-side queries — a generation query queuing ahead of
  a verdict is what killed job `20260730T212901866` at 1731s.
- **S6 lane ladder** — `config.yaml` contradicts its own comments (venture set 2.5 vs 3.2 documented;
  side_hustle 2.5 vs 2.0), making venture the joint-easiest lane. **Founder decision, taken on
  post-Wave-2 data**, so it is a statement about ambition and not a workaround for broken extraction.
- **Money-rail debt:** ledger through `jsonl_atomic.append_jsonl` (`telemetry.py:100` uses a raw
  `FileHandler`); `pricing.py:126`'s hardcoded `4999`; audit #14's `MOAT_PRIMARY` single-operator gap.
- **Publish-side cost, which no cost table contains.** Artifact and content generation fire only on
  PASS, so the zero-pass baseline measured $0 for the stage every one of these changes exists to make
  fire more often. At 8.5%, k=100 means ~8–9 packs of `content_gen` per wave. Price it before Wave 2
  succeeds, not after.

---

## Cut — do not spend an hour on these

| Proposal | Why it is cut |
|---|---|
| Reorder the verdict chain so claude_cli leads | **Already the config.** `config.yaml` reads `[claude_cli, minimax]` with a comment stating the tail is a tail, not a head. MiniMax ruled 24 of 30 checks on 2026-08-13 because claude_cli was walled and standardcompute was dead-marked (`provider_health.json`: strikes 4, *"You've used up your free usage"*). The chain fell through exactly as designed. standardcompute was removed entirely on 2026-08-15 — a tier that answers every call with an out-of-allowance upsell is a guaranteed failure paid before each fall-through, not depth. |
| Remove the G8 critique-revise pass to reclaim spend | **Phantom saving.** `config.yaml:907-908` `critique_revise.enabled: false`; `refinement_enabled` false at `:790`. The money is not being spent. Keep it off — for the rubric-blindness reason, not a savings reason. |
| Revert to deterministic query templates as default | **This repo ran the experiment and it failed.** `config.yaml:157-161` records templates restating the product pitch → off-topic junk → **~93% unverifiable at batch scale**. A gap in the literature is not a refutation of a measurement on this system. |
| Free pre-verify triage that KILLS ~50% of a wave | **Doctrine violation and circular.** An embedding-distance kill cites nothing retrievable; the storefront's only asset is that its kills are receipts. It also trains on the very composites it calls miscalibrated. Shadow-rank with it; publish nothing from it. |
| Decompose the seven checks into finer sub-claims | Measured **−5.3 to −8.9 balanced-accuracy points** with a strong verifier; decomposition helps weak verifiers and hurts strong ones. |
| asyncio · Temporal/DBOS/Postgres · Batch API · multi-agent orchestration | Both designs refused all four independently: one machine, no ops team; Batch API needs raw API-key billing this repo forbids; multi-agent costs ~15× tokens. |
| Re-run the research workflows | 261 KB from 14 agents plus this round's 6 areas / 66 sources are on disk. Resume is same-session only, and those sessions are gone. |

**What both designs refused to change is itself a finding:** seven atomic checks, kill-fast ordering,
the 600-char truncation, deterministic confidence over LLM self-report, source-or-die downgrade,
`MOAT_PRIMARY` finalisation, threads over the flock governor, append-only JSONL. Two architects
instructed to argue opposite cases produced near-identical keep-lists. Fund nothing there — and hold
any future proposal to change those items to a far higher bar.

---

## Rules of engagement

**Three lanes, three worktrees, no more** — the POPDD gate is a HEAD race window and concurrent sessions
clobber each other's index.

- **Lane A — verdict quality:** Waves 1 → 2 → 4. `score.py`, `verify.py`, `retrieval.py`, `config.yaml`.
- **Lane B — throughput:** Wave 3. `run.py`, `run_scheduled.py`, `adaptive.py`, `store.py`, `cli_governor.py`.
- **Lane C — safety, receipts, and W0.1:** Wave 0, then holds the gate for A and B.

Lane A and Lane B both touch `run.py` and `config.yaml`; sequence those specific edits through Lane C.

```bash
git worktree add --detach ../wt-<lane> <ref>
./scripts/setup_worktree.sh ../wt-<lane>     # 4 traps; without it the POPDD gate cannot run
```
- **Never `git add -A`** — `store/` and `storage/` are tracked runtime state pytest writes to.
- Capture a build's own exit status **before** any pipe; `| tail` reports tail's status.
- Money rail, identity, contracts and migrations never leave Claude. Mechanical bulk edits (the 14
  truncation sites, the denylist string, governor logging) are what the cheap executor is for — always
  `pi_gate`, and read the real diff before believing a report.
- One wave, one session; handoff at every boundary. War-room reasoning runs on the escalated model,
  chosen **at session start** — settings are read once at process start, so `/clear` does not apply a
  model change; only relaunching does.

**Definition of done, per item:** the acceptance number before and after from the W0.2 receipt, both
quoted in the commit message, golden set green, daemon still ticking.

---

## What would make this fail

- Funding Wave 3 or Wave 4 before W0.1 returns an AUC. Half the proposals on the table are financed by
  an assumption nobody has tested against the 447 labelled outcomes sitting in the repo.
- Shipping the sufficiency hop on a polarity-blind confidence score — it triggers on the number Wave 1
  is fixing.
- Booking the local-NLI saving. It is the one number in either design that cannot be true at the same
  time as the doctrine.
- Treating local inference as free on the **time** rail: a 0.6B cross-encoder plus a 770M NLI model
  resident alongside 3–8 vet workers is real RAM and real latency inside a 2-hour tick. Free of tokens
  is not free.
- Moving a lane bar early because the pass count is tempting.
- Letting the backlog grow on a walled day, when the trusted-only drain cannot move it.
