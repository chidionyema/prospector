# Commercial Readiness Program

> Started 2026-08-06 from a five-track audit (pack quality/variety, pipeline & k=100, cost/speed
> economics, market research, reliability/recovery) plus founder direction the same evening.
> Like COST_PROGRAM.md and GRAPHIFY_ENFORCEMENT_SPEC.md: append results HERE, not to CLAUDE.md.
> Every number below carries its source; anything not yet proven is marked HYPOTHESIS.

## Founder requirements (2026-08-06, verbatim intent)

1. Vastly improve pack **quality** and **variety** — more AI/tech but broader across the board,
   not just a tech patch; the current catalogue is 78 niches inside ONE meta-shape.
2. **Formats beyond .md files** — real multi-format deliverables.
3. Optimise **cost and speed**; run big batches (**k=100**).
4. **Less reliance on large language models** wherever deterministic computation or small local
   models can do the job (clarified: LLMs generally, not just the coding-agent CLI).
5. **Reliable, robust, elegant recovery from failures**; serious production readiness.

## 0. Measured baseline (all figures from the 2026-08-06 audits)

| Metric | Value | Source |
|---|---|---|
| Live sellable packs | 78 (`decision='pass' AND provisional=0 AND tombstone IS NULL`; decision is stored lowercase) | `store/prospector.db` dossiers table |
| All-time ruled | 1,700: kill 84%, defer 11%, pass 4.6% | same |
| PASS rate today | 11/101 generated ≈ 10.9% across 9 ticks | `store/scheduler/batch_diagnostics.jsonl` 2026-08-06 |
| Metered cost | $0.043/candidate, $0.39/PASS | `tools/spend_today.py` ÷ ledger counts |
| Subscription-equiv cost | **$5.92/candidate, $54.36/PASS**; 99.28% of all compute is subscription CLI | same |
| Time | median **545.6s ≈ 9.1 min/candidate** (3 clean k=15 ticks: 285/546/666s per cand); ~84 min/PASS | `store/scheduler/audit/2026-08-06.jsonl` run_id min/max ts (derived — not a first-party field) |
| Retrieval share of wall time | ~30.5% on the hand-verified run `b5389363b7e1`; remainder unattributed (CLI spawn + reasoning) | same |
| k=100 single-run projection | 7.9–18.5h wall (median 15.2h); ~$4.27 metered; ~$592 subscription-equiv | linear at `claude_concurrency=4` (`config.yaml:150`), `vet_workers=3` (`:154`) |
| Concurrency knee (pre-cursor_cli-removal) | N=8 CLI slots: 5.3x vs N=2; N=14 only +13% over N=8 | memory `pipeline-speedup-2026-07-31.md` — needs re-probe |
| Tech ideas in catalogue | 7/78 titles with any tech keyword; 0 tech sector facet. Tech candidates PASS at 10.1% vs 4.8% base (n=1,511) — **never proposed, not killed** | `store/prospector.db` queries, quality audit |
| Live-catalogue hygiene | 51% blank ambition_tier; 34/63 prod oneLines truncated mid-word (write-side fixed, rows dirty); one live pack has a refuted `claims_verifiable` under a ✅ PASS banner; one has £/$ mixed on its headline revenue line | quality audit: `store/dossiers/0f2109fb198341a4.pass.json`, `c8fbb7aa12e1bf48` `04_Financial_Model.md` |
| Market price anchors | single PDF report $295 (Kentley); idea DB $499–$2,999/yr (IdeaBrowser, tiers by report VOLUME); CSV export gates the $39→$99/mo jump (Exploding Topics) | market track, URLs in §6 |

## 1. Why yield is zero right now (diagnosis, drives Experiment E1/E2)

Not a generation collapse — a grounding-coverage failure on two checks. Last batch:
`payer_solvency` unverifiable 11/15, `distribution` 10/15 — exactly the smb/growth lanes'
`moat_critical_checks` (`config.yaml:404/455`) — while `pain_reality` grounds fine (2/15).
7/15 kills were `moat_ungrounded`; only 2/15 died on actual disconfirming evidence. Candidates are
dying from ABSENCE of citable evidence on two specific check types, not from being bad ideas.
(Source: `store/scheduler/DIAGNOSTICS_LATEST.txt`, pipeline audit.)

## 2. Solution designs

### 2.1 Variety — coverage-driven generation (the proper fix, not a config patch)

Proven mechanics: the daemon runs permanent blue-sky (`run_scheduled.py:649` passes an empty
signal), never touching `discover_signals()`; topic selection is `structural_forms` ×
`audience_forms` (`config.yaml:713`) and **all 8 audience personas are consumer/regulated-worker
archetypes**; `discover.py:18-21`'s sector list (unused by the daemon anyway) has no
technology/software entry; `adaptive.py:252-268` enforces ≥6 sectors per batch, which produces
niche variety inside one meta-shape (individual-vs-bureaucracy claims/compliance recovery).

Design — deterministic steering, LLM only fills the brief (also serves the less-LLM goal):

- **V1 Taxonomy in config** (params-in-config rule): a real 3-axis taxonomy — `sectors` (add
  technology/software/AI/developer-tools AND broaden: creator economy, climate/energy services,
  health-adjacent, B2B ops, data/API products…), `audience_forms` (add operator/buyer personas:
  startup operator, developer, agency owner, ops manager, e-commerce seller… keep the consumer
  personas), `structural_forms` (keep the 20). Nothing hardcoded in `discover.py`.
- **V2 Coverage sampler**: before each tick, query `store/prospector.db` for the catalogue + recent-
  candidate distribution over (sector × persona × tier × market), and pick the batch's target cells
  by under-coverage (quota/entropy sampling — pure Python, zero LLM). The generation prompt receives
  the CELL as a constraint; the LLM's creativity operates inside it. This replaces "avoid recent
  titles" steering-by-prompt with steering-by-sampler.
- **V3 Signal mode**: alternate blue-sky ticks with signal-driven ticks that call
  `discover_signals()` on live retrieval (the ddg/exa chain already exists) so topicality is
  grounded, not imagined. Ratio in config.
- **V4 Meta-shape monitor**: nightly job embeds one-liners (local model, §2.4) and alerts when the
  top cluster exceeds a configured share — the "78 niches, one shape" failure becomes measurable.

### 2.2 Quality floor — deterministic pack linter + refuted-check fence

The ceiling is fine (business-plan-grade output with ~20 citations); the floor is a commercial
liability. Two mechanisms, both non-LLM:

- **Q1 Refuted-check fence**: a candidate with ANY `refuted` check must not ship under a clean ✅
  banner. Recommendation (needs founder sign-off, it tightens "publish only on PASS"): refuted
  `claims_verifiable` → treat as hard fail (truth veto per the two-loops rule); any other refuted
  soft check → mandatory "Adversarial findings" block in `00_Executive_Summary.md` AND the
  storefront listing, rendered from the dossier's own data in `dossier.py`/`pack_html.py`.
  Receipt for why: `0f2109fb198341a4` ships ✅ PASS with "the sources contradict this" at line 98
  of `QA_Report.md` and a named accredited £300 incumbent found by its own adversarial pass.
- **Q2 Pack linter** (pure Python, blocks publish, extends the self-debug directive): currency
  symbols consistent with `candidate.market` (the £/$ defect); arithmetic re-check of every
  computed line in `04_Financial_Model.md`; no mid-word truncation; citation URLs resolvable
  (bounded, cached); required sections present; no empty artifacts. Wire as a publish gate in
  `bridge.py` with a machine-readable lint report saved next to the dossier.
- **Q3 Backfills**: blank `ambition_tier` (40/78 rows) and the 34/63 truncated oneLines
  (`tools/backfill_listing_copy.py` exists on this branch; the republish is a money-rail operation
  — run it deliberately, not as a side effect).

### 2.3 Formats — ship the data we already compute (deterministic rendering)

Buyers currently get 8 .md files + 1 static HTML render (`bridge.py:98-105`, `pack_html.py`). The
pipeline already computes and discards exactly what the market pays more for (§6: CSV export gates
Exploding Topics' $39→$99 jump; spreadsheet artifacts sell $70–99 standalone):

- **F1 `scorecard.json` + `financials.json/.csv` + `comparables.json`** in every bundle —
  the six-axis `ScoreResult` (`models.py:299`), the Python-computed financial model inputs/outputs,
  and the `PriceAnchor` comparables already fetched at `bridge.py:539` and then discarded.
- **F2 Score radar + key charts as static SVG** — deterministic matplotlib/SVG, no LLM.
- **F3 XLSX financial model** (openpyxl): the model's verified inputs as an editable sheet with
  formulas, so the buyer can re-model. This is the single highest-priced format precedent found.
- **F4 PDF** render of the pack (headless print of the existing HTML).
- **F5 Storefront credibility mechanics** (market-sourced): methodology page, one full free sample
  pack, dollar-denominated guarantee, clickable inline citations (the named weakness of the $2,999/yr
  category leader). HYPOTHESIS worth an A/B: publishing the kill log as a trust signal — no
  competitor does it; untested as a conversion lever.
- Later: machine-readable export TIER and a "vet my own idea" product (IdeaBrowser validates
  $1,499/yr for 3 custom reports/mo; our moat already does exactly this per candidate).

### 2.4 Less-LLM architecture — what comes off the model

Principle: the LLM is only irreplaceable where judgement is (verdict + adversarial, MOAT_PRIMARY).
Everything else moves to deterministic Python or small local models, which is simultaneously the
cost, speed, reliability and quality-floor play:

| Stage | Today | Target | Mechanism |
|---|---|---|---|
| Query generation | LLM on the moat (`verify.py:233/606`) | **Hybrid: templates per check type** (slot-filled from candidate fields) + LLM expansion where a template draws blank | May fix §1 — payer_solvency/distribution queries name concrete payer entities by construction. CAVEAT (§7): fact-checking literature trends TOWARD LLM query-gen; no template-vs-LLM benchmark exists, so E1 is our own engineering A/B, not literature-backed |
| Dedup | char-ratio + token-Jaccard (`dedup.py:106`) | + local embeddings (sentence-transformers class model, on-device) | no API, durable "embed-match" intent |
| Prescreen prefilter | LLM (`fast_op`) | embedding-similarity prefilter drops obvious near-misses BEFORE any LLM call | LLM only on survivors |
| Financial model | Python-computed already | keep; extend to all numeric artifacts + F1/F3 outputs | zero LLM |
| QA | LLM-written QA report | + deterministic pack linter (Q2) as the publish gate | zero LLM |
| Rendering/formats | markdown + HTML | all §2.3 formats deterministic | zero LLM |
| Diversity steering | prompt-side "avoid" lists | coverage sampler picks the cell (V2) | zero LLM |
| Verdict + adversarial | moat | **stays moat** — the irreducible core | — |

### 2.5 k=100 — throughput plan

Constraints (audit-proven): wall clock, not money — 7.9–18.5h/run at `claude_concurrency=4`;
metered cap sits at 0.72% utilisation; a k=100 run concentrates ~$592 subscription-equivalent into
one batch (likely trips the Max-plan cap, threshold unverifiable — not written down anywhere).

- **S1 Re-probe the concurrency knee** (E3): repeat the 2026-07-31 N-probe at N=4/6/8 post-
  cursor_cli-removal; raise `claude_concurrency`/`vet_workers` in lockstep to the knee. Expected up
  to ~2x wall clock; the prior collision-at-2 fix (`claude_cli.py:150-152` per-slot stable cwd)
  must be load-tested at the new N, not assumed.
- **S2 Fund the metered API operator** — config only: `ANTHROPIC_API_KEY` + add `claude` to
  `config.yaml:36` operator chain. The key-based `ClaudeOperator` exists and is already in
  MOAT_PRIMARY (`operator.py:161-183`, `:889`, dispatch `:1027-1035`). This removes the CLI-
  subprocess ceiling AND the subscription cap from the k=100 path, and unlocks prompt caching.
  Upper-bound cost if the ENTIRE pipeline ran metered Sonnet: ≈$124/day at k=100 (intro pricing,
  whole-batch token profile — verdict-only share needs E4's instrumentation).
- **S3 Batch API for overnight k=100** — VERIFIED 2026-08-06 (docs.anthropic.com, §7): 50%
  discount; most batches complete <1h, 24h expiry (expired requests unbilled); 100k requests or
  256MB per batch; a SEPARATE rate-limit pool from the Messages API; prompt caching STACKS with
  batch (best-effort 30–98% hit rate — use 1-hour TTL `cache_control`, not 5-min); **server-side
  web search and tool use work inside batch**, so grounded verdict calls can run batched. Shape:
  the live daemon keeps interactive DEFER/resume semantics; a second batch-only operator runs
  nightly bulk vets. Estimated $4–9 per k=100 bulk-vet run (HYPOTHESIS — assumed token counts;
  E4 measures the real ones). Note: metered API is a genuinely new cost line vs the subscription,
  compatible with the no-hosted-service rule (which is about infra, not API calls).
- **S4 Hybrid parallel verdicts**: keep kill-fast for the two cheapest decisive gates, then run the
  remaining checks + adversarial concurrently for survivors. Preserves most of kill-fast's savings
  (most kills die early — §1) while cutting the 8-sequential-round-trip tail for the candidates
  that matter. Verdict-path change → design + review stays in Claude, per the fence.
- **S5 Cross-tick retrieval cache**: `retrieval.py` caching is breaker state, not a persistent
  result cache; ~30.5% of wall time is retrieval. Content-addressed on (provider, query) with TTL.
- **E4 Per-stage token/cost instrumentation is the prerequisite** for honest S2/S3 economics: tag
  every operator call with a `stage` field; diagnostics currently attribute by provider only.

### 2.6 Reliability P0s (from the recovery audit; branch `fix/durable-ledger-fence` already fixed
decay wiring, absolute limit-reset parsing, Telegram sink, truncation write path, watchdog)

- **R1 CRITICAL — moat-blind ticks never alert.** `alerts_for_tick` (`alerts.py:369`) has no
  `moat_blind` branch (probed live: returns `[]`) and `moat_blind` is not in `TELEGRAM_KEYS` —
  two changes + the already-written failing repro as the test. The engine's most severe state is
  currently log-only.
- **R2 Per-candidate claim lock** for drain/decay/resume (mirror `health.py:130-153`'s file-locked
  probe) — concurrent drain + manual resume can pay twice for the same re-vet.
- **R3 Atomic appends** for `alerts.jsonl`/`ticks.jsonl` (tmp+rename or fsync + tolerant reader) —
  the torn-write defect class that has bitten twice before.
- **R4 Restore drill** for `prospector.db` + dossier tree: script that restores the latest backup to
  scratch and asserts row count + spot-check. `backup_store.py` has zero verification today.
- **R5 End-to-end synthetic-failure harness**: force each classified exhaustion shape through
  `FallbackOperator` → assert health marks, moat-blind, and (post-R1) the alert — the classifier is
  unit-tested; the seam is not.

## 3. Experiment register

| ID | Hypothesis | Method | Metric / kill criterion |
|---|---|---|---|
| E1 | Hybrid template+LLM queries naming concrete payer/channel entities cut `payer_solvency`/`distribution` unverifiable rates | Instrument `verify.py:241/276` query logging; A/B hybrid vs current LLM query_gen on 2 batches | unverifiable rate on those checks; PASS rate. Kill if no drop (literature gives no prior either way, §7) |
| E2 | B2C personas are structurally ungroundable for smb/growth critical checks | Cross-tab `moat_ungrounded` kills × `audience_forms`; then bias 2-3 batches toward operator/B2B personas | PASS-rate delta by persona class |
| E3 | Concurrency knee is still ~N=8 post-cursor_cli | Re-run the 2026-07-31 probe at N=4/6/8; then one clean k=15 tick at the knee | p50 call latency, tick wall time, zero collisions |
| E4 | (instrumentation, not a bet) per-stage tokens make S2/S3 economics computable | `stage` field on operator/token counters; one batch | verdict-share of tokens known |
| E5 | Coverage sampler lifts sector/persona entropy without PASS-rate loss | V2 on for 3 batches vs 3 control | distribution entropy; PASS rate |
| E6 | Local embedding prescreen prefilter drops ≥20% of LLM prescreen calls at no PASS loss | shadow-mode first (log, don't act) | agreement with LLM prescreen on kept/dropped |
| E7 | Kill-log visibility converts (marketing) | storefront A/B kill-log visible vs hidden | conversion rate |
| E8 | Batch API halves bulk-vet metered cost | pending research-track fact sheet; then one real k=15 batch via batch API | $/candidate vs S2 interactive |

## 4. Sequencing

- **P0 (days)**: R1 alert fix · E1/E2 (yield — the engine currently produces nothing) · Q2 linter
  (currency/truncation/arithmetic) + Q1 surfacing · V1 taxonomy broadening · E3 knee probe · E4
  instrumentation.
- **P1 (1-2 weeks)**: S2 API operator + caching · V2 sampler + E5 · F1-F4 structured formats ·
  R2/R3/R5 · Q3 backfills (deliberate money-rail op).
- **P2 (weeks)**: S3 batch-API k=100 nightly · S4 hybrid parallel verdicts · embeddings dedup +
  E6 · F5 storefront credibility + E7 · export tier / "vet my idea" product · R4 restore drill in
  cron.

## 5. Fences that do not move

Verdict-from-retrieval-only; MOAT_PRIMARY only rules; KILL-with-receipt is first-class; demand
never overrides truth; params live in config; unattended generation only behind the spend cap +
PAUSE rails. Everything in this programme routes AROUND the moat, never through it.

## 6. Market receipts (fetched 2026-08-06)

- Exploding Topics pricing — CSV export gates $39→$99/mo, API gates $249/mo: explodingtopics.com/pricing
- IdeaBrowser $499/$1,499/$2,999/yr, tiers by report volume; reviewer-named weakness "individual
  claims not linked" to sources: preuve.ai/compare/ideabrowser
- Kentley Insights $295/report, named methodology + samples + $-denominated guarantee:
  kentleyinsights.com/free-market-research-reports/
- Starter Story Academy $499/yr: build.starterstory.com/checkout?plan=academy
- Trends.co $300/yr, >10k subscribers pre-sunset: prnewswire.com (launch release)
- Gumroad financial-model artifacts $69.95–$99 standalone: rokugene.gumroad.com/l/financialmodel
- Maven: $950+ courses earn 50-100% more per visitor; price scales with live hours + project depth:
  help.maven.com/en/articles/6732396
- No competitor found publishes a kill log or rejection rate (absence checked across the set above).

## 7. Research fact sheet (fetched 2026-08-06 unless marked)

**Batch API** (platform.claude.com/docs/en/build-with-claude/batch-processing.md, live-fetched):
50% off standard Messages pricing; most batches <1h, results at completion or 24h; unfinished
requests expire at 24h and are NOT billed; 100,000 requests or 256MB per batch; results retained
29 days; separate rate-limit pool from Messages ("does not affect rate limits in the Messages
API"); caching discounts STACK with batch — cache hits are best-effort under concurrent
processing, observed 30–98%; use 1-hour TTL for batch (5-min entries can expire mid-batch);
**all server tools supported in batch including web search** (the batch worker runs the same
server-side agentic loop). Not supported: streaming, cache pre-warming, `store`.

**Prompt caching** (claude-api skill cache 2026-06-24 — re-verify before budgeting): cache read
≈0.1× input rate; write 1.25× (5-min) / 2× (1-hour); minimum cacheable prefix 1024 tok on Sonnet
tier. Sonnet 5 intro pricing ($2/$10 per M) ends **2026-08-31** — reconfirm rates then.

**Local embeddings** (for dedup/prescreen/meta-shape monitor, all API-free): nomic-embed-text-v2
(137M, ~274MB, MIT, 8192-tok context, runs on CPU); Qwen3-Embedding-0.6B (MTEB-eng-v2 70.7,
Apache-2.0, ~1.5GB, Ollama-native); BGE-M3 (568M, multilingual, pairs with bge-reranker-v2);
qwen3-embeddings-mlx proves Apple-Silicon local serving at 44K tok/sec.

**Diversity selection methods** (for V2/V4): MMR (Carbonell & Goldstein 1998) — tunable
relevance/diversity reranking; SMMR (SIGIR 2025) — cheaper sampling variant; DPP-based selection
for LLM inputs/outputs (LM-DPP, arxiv 2408.02103; Reliability-Aware DPP, arxiv 2602.00885) —
direct precedent for "deterministic sampler picks, LLM fills." Coverage/quota sampling over a
taxonomy is standard stratified sampling; no dedicated citation needed or found.

**Negative finding, kept on purpose**: no source benchmarks slot-filled template queries against
LLM query generation for retrieval quality, and 2025 FEVER-workshop systems use LLM-generated
queries per subclaim (aclanthology.org/2025.fever-1.20). The template case is an engineering
argument (determinism, cost, §1 targeting) that E1 must prove or kill on our own data.

**Unverifiable, carried openly**: real batch cache-hit rate for our traffic; real per-stage token
counts (E4); the Max-plan subscription cap threshold (documented nowhere found); Sonnet 5 rates
past 2026-08-31.

## 8. E2 baseline receipts (measured 2026-08-06 ~22:15Z, full dossier history)

One-shot cross-tab over `store/dossiers/*.json` (script in session log; re-runnable). N=1,511
dossiers: 1,285 kill / 148 defer / 78 pass. CAVEAT: full history spans several query-gen eras, so
this is the BASELINE for E2's controlled batches, not the A/B itself.

- **Grounding starvation confirmed at scale** (was 11/15 and 10/15 on one batch): on killed
  persona-tagged dossiers, `payer_solvency` = 771 unverifiable / 145 supported / 49 refuted;
  `distribution` = 652 unverifiable / 263 supported / 6 refuted. The two E1 target checks are
  starved 5:1 and 2.5:1 against supported.
- **Persona class moves PASS rate ~9x**: smb_owner 21/242 (9%), gen_z_worker 18/221 (8%),
  primary_carer 15/214 (7%), manual_tradesperson 11/173 (6%), squeezed_middle 5/105 (5%),
  retiree_cohort 3/100 (3%), public_sector_worker 2/148 (1%), freelancer_creative 2/135 (1%).
  Consistent with E2's hypothesis; the operator/B2B-persona arm (V1) should beat the 1% tail.
- 98% of dossiers carry an audience persona tag, so the cross-tab is not selection-biased by
  missing tags (24 kills + 1 pass + 1 defer untagged).

## 9. Kill-gate validity audit (2026-08-06, founder challenge: "kill gate determining quality is an assumption, not a fact")

Decomposition of all 1,288 kill dossiers (`store/dossiers/*.kill.json`, 2026-06-15 → 2026-08-06),
by what the firing gate actually rested on (script: session 2026-08-06, re-runnable — categories
derived from `gate_fired` + `reason` + per-check verdicts):

| Category | n | share | meaning |
|---|---|---|---|
| COMPOSITE, mostly unverifiable (≥50% checks unverifiable; median 83%) | 519 | 40.3% | score computed over absence |
| EVIDENCE (grounded refuted verdict fired) | 229 | 17.8% | the only unambiguous quality reading |
| ABSENCE (`moat_ungrounded` / `source_or_die`) | 190 | 14.8% | explicit no-evidence kills |
| ADVERSARIAL (`adversarial_decisive`, LLM judgement) | 142 | 11.0% | groundedness not yet audited |
| COMPOSITE, mostly grounded | 82 | 6.4% | plausibly real quality reading |
| unparsed single-gate reasons (incumbency 53, value_durability 30, …) | ~123 | ~9.5% | reason string didn't match refuted/supported pattern |

Key receipts:
- **266 kills fired `min_composite` while 100% of their checks read `unverifiable`** — the
  composite that killed them was computed from zero grounded evidence.
- Of the 229 evidence kills, **61% fired at confidence < 0.5** (median 0.43, p90 0.70) — and
  `confidence_floor: 0.0` (`config.yaml` thresholds) is inert, so conf 0.40 hard-kills.
- Verdict base rates on the killer checks: payer_solvency 785 unverifiable vs 49 refuted;
  distribution 665 vs 6; incumbency 674 vs 203. Absence outnumbers disconfirmation ~10:1.
- Polarity leads: `incumbency` firing on `supported` is BY DESIGN (`kill_filter.py:40` — a real
  incumbent). But 2 `legality` kills fired on `supported` whose rationales say the activity IS
  legal ("completely legal to grow, sell", "does not require a specific licence").
  HYPOTHESIS: legality claim phrasing inverts polarity in some template path. Check: read the
  legality claim text in those two dossiers + `prompts.py` claim framing.

**Consequence for the programme**: at most ~24% of kills (EVIDENCE + composite-mostly-grounded)
are readings of idea quality; ≥55% are readings of retrieval coverage. Any generation-quality
experiment scored by kill-rate is measuring the retriever. Order of work therefore: fix the
instrument (E1 query-gen coverage, confidence-floor calibration) BEFORE steering generation by
kill outcomes. Note the cross-run avoid-list already feeds kills back into generation
(`generate.py:133-144` seeds prior kill titles as "avoid") — i.e. absence-of-evidence kills are
already steering generation away from idea families that were never actually disproven.

New experiments for the §3 register:
- **E9 kill reproducibility**: re-vet a random sample of ~20 kills unchanged; % that reproduce
  the same gate = the instrument's noise floor. Kill criterion for trusting kill-rate as a
  metric: <70% stable.
- **E10 false-kill audit (external ground truth)**: sample ~30 kills; for each, one bounded
  retrieval pass asking "does a real business do exactly this profitably?" A cited yes = false
  kill. This is the first validation of the gates against reality rather than fixtures.
- **E11 confidence-floor calibration**: replay the 229 evidence kills at floors 0.4/0.5/0.6
  (data already on disk, zero LLM) and report how many hard kills fall through to scoring.
- **E12 adversarial groundedness**: audit the 142 `adversarial_decisive` kills for whether the
  decisive claim cites a passage or is pure model opinion.

## 10. Why the evidence is absent (root-cause decomposition, 2026-08-06)

All 7,405 checks across 1,511 dossiers: 4,947 (67%) unverifiable. Cause buckets (per-check
`retrieval_failed` / `degraded` / `sources` fields):

| Bucket | n | share |
|---|---|---|
| A. retrieval_failed (infra) | 196 | 4.0% |
| B. degraded chain | 300 | 6.1% |
| C. zero passages retrieved | **0** | **0.0%** |
| D. passages retrieved, judge ruled not probative | 4,451 | 90.0% |

**Retrieval coverage is NOT the bottleneck** — bucket C is empty; retrieval always returns
something. 90% of absence is the judge (correctly, per sampled rationales) ruling that retrieved
passages don't address the claim. Infra (A) concentrates in value_durability (119/196, outage-era).
Provider-era confound: 62% of unverifiable verdicts were ruled by brains no longer on the moat
(deepseek 1,997, cursor_cli 618, gemini_cli 449) — validity experiments (E9/E10) must run on the
current moat only.

Two mechanisms produce bucket D (receipts: 12 sampled query→rationale pairs, session 2026-08-06):

- **R1 — the question class is unanswerable in principle.** payer_solvency and distribution ask
  the web direct questions about a product that does not exist: "will UK freelance designers pay
  for X", "what route reaches SMB owners for the AI negotiator tool". Every sampled rationale has
  the same shape: *passages cover adjacent real facts, none address willingness-to-pay / route for
  THIS product*. No retriever fixes this; the open web does not publish that passage.
- **R2 — templated disconfirmation suffixes on keyword salad.** `verify.py:59-60` and `:184-185`
  append fixed strings ("`{q} budget cuts OR cannot afford OR insolvency`", "`{q} customer
  acquisition channel saturated OR expensive`") to the candidate one-liner, producing queries like
  "solo-operated audits care home top fee customer acquisition channel saturated OR expensive" →
  tangential passages (Oxford library catalog, stock images).

**Design implication (E1 is hereby reframed).** The fix is not template-vs-LLM query generation
for coverage — it is making the CLAIM answerable, i.e. proxy evidence classes the web does
publish. The in-repo precedent is `price_comparables.py`: evidence-only, cites prices buyers
ALREADY pay. Same move for the two dead checks:
- payer_solvency → "buyers in this segment currently pay for an adjacent/comparable product"
  (cited price/spend evidence, named payer entities in the query, not the hypothetical product).
- distribution → "a named channel that reaches this segment exists" (community, marketplace,
  association, trade body — citable).
**E13**: replay ~30 unverifiable payer_solvency/distribution checks with proxy-framed claims on
the current moat; metric = grounded-rate (supported OR refuted). Kill criterion: <2x improvement
over the 10:1 absence ratio means the reframe is wrong too.

**Terminal-state honesty.** 266 candidates were KILLED with 100% unverifiable checks — the
project rule says "a KILL is not the model's opinion; it is evidence", and absence is not
evidence. The honest terminal state for evidence-absence is *unpublishable, parked for re-vet
under answerable claims* (the DEFER philosophy), not a kill dossier that reads as a verdict.
After the claim reframe ships, the ~700 absence-kills (§9 categories 1+3) are RE-VET candidates —
cheaper than regeneration, the candidates are already on disk. The avoid-list stays as-is: its
job is anti-duplication (don't re-pay generation for families already on disk), which is valid
for kills too; the poison was the terminal KILL label, not the avoidance.

## 11. Hallucination safeguards & the small-model acid test (2026-08-06)

**Verdict-layer rails are structural and measured holding.** `verify.py:384-388` filters model
citations to the actually-retrieved source ids and downgrades `supported`-with-no-valid-citation
to `unverifiable`; confidence is computed FROM citations (`verify.py:70-133`), so an uncited
ruling cannot score high. Measured across all 7,405 persisted checks: **0 citations reference a
source_id outside the check's own retrieved set** (by construction — the filter runs before
persist) and only 6 ruled verdicts (0.24%) carry zero citations. `price_comparables.py:104` adds
the strictest rail in the repo: a number must literally appear in the cited passage.

**Where hallucination risk actually lives (ranked):**
1. **Artifact layer (weakest).** The 8 pack .md files are free-written LLM prose; no
   deterministic check ties their claims to passages. Known escapes: `0f2109fb198341a4` ships a
   ✅ PASS banner over "the sources contradict this"; £/$ inconsistencies; 34/63 truncated
   oneLines. Fix is already designed: Q2 pack linter + Q1 refuted fence (§2.2) — this section is
   the receipt that they are the *hallucination* controls, not just polish.
2. **Rationale semantic fidelity (unfenced).** A rationale can cite a real source_id yet
   misdescribe the passage. Only the adversarial pass and the moat-primary judge stand against
   this; no deterministic rail. HYPOTHESIS-level exposure — measurable by an entailment spot-audit
   (sample N rationales vs their stored passages).
3. **Refuted-with-zero-citations edge**: the `:388` downgrade covers `supported` only; 6 historic
   `refuted` rulings carried no citations, and with `confidence_floor` inert they could in
   principle fire a gate. Folds into E11.
4. **Generation layer: risk ≈ 0 by design** — ideas are hypotheses; everything downstream must
   ground them.

**The acid test (MiniMax runs the workflow).** Existing measurements say NOT yet, for the
judgement stages: all 5 provisional passes ruled by non-moat brains were KILLED on moat re-vet
(memory: `provisional-passes-all-killed-on-revet.md`), and MiniMax is non-deterministic on
structured routing at temperature 0 (4/6 candidates changed tier across 3 repeat runs). But
"whole workflow" is the wrong unit — the right long-term play is already §2.4: shrink the judged
surface deterministically, then substitute per stage with the moat as referee:
- **E14a verdict-substitution replay (zero retrieval cost)**: every ruled check's passages are on
  disk; re-judge a sample with MiniMax and score agreement vs the moat's verdict per check type.
  Ship criterion per stage: ≥95% agreement on refuted (a false refuted kills someone's idea),
  looser on unverifiable.
- **E14b adversarial substitution**: same replay pattern on the adversarial pass.
- Sequencing insight: **E13's claim reframe makes the acid test winnable.** Answerable claims
  turn the verdict task from open-ended judgement into passage-entailment ("does this passage
  state that buyers pay £X?") — exactly the task class where small models close the gap on
  frontier ones. Run E14a BEFORE and AFTER E13 to measure how much the reframe shrinks the
  frontier premium. The MOAT_PRIMARY fence does not move until E14 agreement data says so.

## 12. Live observability in the Telegram cockpit (founder ask 2026-08-06: "not a black box")

Recon receipt: the Hermes cockpit ALREADY has a full Prospector control panel
(`~/.hermes/hermes-agent/gateway/operator_shell/prospector_daemon.py:669`,
palette button in `command_palette.py:120`, natural-language pause/restart in
`natural_ops.py:360-470`, tests in `test_prospector_daemon.py`). The black-box gaps are:

- **O1 `/prospector` command** — one `CommandDef` in `hermes_cli/commands.py:~135`
  (`aliases=("pd",)`), panel already registered in `estate.py:337` `_PANELS`.
- **O2 Push alerts (the big one)** — NOTHING watches `store/scheduler/alerts.jsonl`; the
  2026-08-06 "Zero yield: 15 candidates, 0 PASS" warning was written and never delivered. Add an
  async watcher in the gateway (pattern: `run.py:12793 _run_process_watcher`; sender:
  `notify_fanout.py:29 fanout_p0`) tailing alerts.jsonl by byte-offset (state file), pushing:
  every new alert row; every PASS published (the happy path deserves a push); heartbeat stale
  >90min while phase≠idle (stall); daemon serving old code (probe's existing heuristic).
- **O3 "Now" live view** — a sub-view on the existing panel reading what's already on disk:
  `heartbeat.json` (phase, pid, batch_size — updated at every phase change,
  `run_scheduled.py:141`), tail of `store/scheduler/audit/<today>.jsonl` (per-check
  `verify_search` events carry candidate_id + check — moment-to-moment progress EXISTS, it's
  just unread), `DIAGNOSTICS_LATEST.txt` funnel block (last run: generated→vetted→decisions,
  closest-to-pass titles), spend line via `tools/spend_today.py` logic, backlog count.
- **O4 Prospector-side: decision events.** Audit jsonl has search-level events but (verify at
  implementation) likely no `candidate_decided` / `pass_published` rows. Emit one structured
  event per candidate decision (id, title, decision, gate_fired, composite) and per publish —
  this is what O2/O3 consume for "what was produced, moment to moment".
  Panel render contract: return `(text, buttons, ok)` — `ok=False` when the read fails
  (preflight cache fix 2026-08-06).

## 13. Remaining major levers not yet in the programme (ranked, 2026-08-06)

- **L1 Evidence corpus reuse.** Every check's passages persist on disk (7,405 checks, ~6
  sources each). Build a local passage store + embedding index; before live retrieval, serve
  from corpus when fresh-enough. Wins: cost, latency, immunity to the 10% infra/degraded bucket,
  and makes the ~700-kill re-vet after E13 mostly retrieval-free. HYPOTHESIS to size first:
  measure query/topic overlap across candidates before building (if <20% of checks could ever
  hit the corpus, don't).
- **L2 Demand-loop telemetry into the coverage sampler.** The two-loops rule keeps truth
  sovereign, but the demand loop currently feeds NOTHING back: storefront views/purchases per
  sector×persona×tier could weight V2's coverage-sampler cells (offer more of what sells) with
  zero contact with verdicts. Needs storefront analytics first (views exist? verify).
- **L3 Self-executing experiment harness.** E9–E14 are registered but manual. A
  `tools/experiments/` runner per experiment that writes receipts (JSON + doc append) makes the
  programme run itself and keeps the source-or-die discipline mechanical.

## 14. ML architecture v2 — the entailment gate and the escalation ladder (research 2026-08-07)

The artifact-hallucination gap, the rationale-fidelity gap, the MiniMax acid test and per-verdict
cost all resolve with ONE architectural move: a small, local, Apache-licensed entailment checker
between every generated sentence and its cited passage. The verdict step of this pipeline is
exactly what a whole model class was built for, with published parity vs frontier judges:

- **Vectara HHEM-2.1-Open** — 110M, Apache-2.0, <600MB RAM, ~1.5s/2k tokens on plain CPU; model
  card shows it BEATING GPT-4 on AggreFact-SOTA (+2.64) and RAGTruth-Summ (+1.80) balanced
  accuracy. https://huggingface.co/vectara/hallucination_evaluation_model
- **MiniCheck-Flan-T5-Large** — 770M, GPT-4-level grounding verification at ~400x lower cost
  (EMNLP 2024), repo Apache-2.0, runs via Ollama. https://arxiv.org/abs/2404.10774
- **bge-reranker-v2-m3** — 568M, Apache-2.0: the evidence-selection stage (retrieve broad,
  rerank to top-k before judging). https://huggingface.co/BAAI/bge-reranker-v2-m3
- License trap: the two top leaderboard models (Bespoke-MiniCheck-7B 77.4% on LLM-AggreFact,
  Patronus Lynx 8B) are **CC-BY-NC** — not usable commercially without a licence. The clean
  local stack is HHEM + MiniCheck-T5 + bge-reranker.
- Claim decomposition before checking: +6.0 factual F1 / +7.35 bal-acc measured
  (https://arxiv.org/html/2604.11036), but only on complex inputs — skip for atomic claims
  (https://arxiv.org/html/2411.02400v1).

**The three seams it closes:**
1. **Artifact compilation (better than a linter — stop free-writing).** Packs become
   claims-with-receipts: every factual sentence is either rendered deterministically from
   dossier JSON (scores, financials, comparables — already computed) or is a bounded LLM prose
   slot carrying citation ids. The entailment gate then machine-checks every cited sentence
   against its stored passage; a failing sentence blocks publish. Q2's linter checks format;
   this checks TRUTH. `0f2109fb`-class escapes become structurally impossible.
2. **Rationale fidelity (the unfenced gap).** At verdict-persist time, gate the judge's
   rationale against its cited passages; low entailment → downgrade to unverifiable + flag.
   Deterministic, zero tokens, closes the "cites a real id, misdescribes the passage" hole.
3. **Escalation ladder (the change of approach).** retrieve → rerank (bge) → small-model
   entailment score → frontier LLM only composes the final three-way verdict and rules the
   ambiguous middle band. Small models emit supported-probability, not
   supported/refuted/unverifiable-with-citations — so the moat stays the composer (MOAT_PRIMARY
   fence intact) while ~everything mechanical moves local. This is the E14 acid test made
   concrete: the exit from frontier models is a LADDER, not a swap.

**New experiments** — E15 (FREE, first): run HHEM over the existing dossiers' claim-citation
pairs vs their cached passages = a zero-token groundedness audit of the entire live catalogue;
also yields the measured rationale-infidelity rate (§11 gap 2). E16: bge-rerank the stored
passages of bucket-D checks — does better evidence selection move unverifiable→ruled? E17:
HHEM/MiniCheck agreement vs moat verdicts on the 2,458 ruled checks (sharpens E14a with named
models). All three run on data already on disk.

## 15. Leading-product position (market research 2026-08-07; competitor-authored sources flagged in agent log)

Category state: bifurcated into unsourced discovery catalogs (IdeaBrowser $499–$2,999/yr; central
published criticism: claims not linked to sources) and cheap one-shot AI reports racing on
citation COUNT (DimeADozen $129 "800+ citations", Preuve $29 + $19/mo re-scan). Citation volume
flipped to table stakes; nobody warrants their claims are TRUE — all guarantees are
satisfaction-based. Cheapest real API is enterprise-priced (Exploding Topics $1,000–$4,000/mo).

Open gaps that map 1:1 onto what we already have or are building:
- **P1 Verifiability guarantee** (needs §14): "every claim machine-checked against its cited
  passage — refund if a citation fails." Enforceable only with the entailment gate; incumbents
  cannot copy it without rebuilding. No competitor offers an accuracy-based guarantee.
- **P2 Re-verification SLA as a product**: the SLA re-vet rail exists (commit e9d3a8b); market
  equivalent is one vendor's $19/mo re-scan. Sell freshness: "evidence re-checked every N days
  or the pack is unlisted."
- **P3 Public kill log**: no commercial equivalent anywhere in the survey — the honest-negative
  posture ("we'll tell you it's dead and show the evidence") is unoccupied and we already
  render KILL dossiers first-class.
- **P4 Programmatic vetting API** at non-enterprise price ("vet my own idea" per-call): only
  enterprise-priced competition; our moat already does this per candidate.
Caveat: several competitor facts are competitor-authored pages — spot-check against vendors'
own pricing pages before any marketing copy quotes them.

## 16. P0 delivery log (branch `feat/p0-r1-e1-v1`, base e9d3a8b; verified 2026-08-07 05:1xZ)

Five commits, pushed. Receipt for the whole branch: `896 passed, 2 skipped in 28.05s`
(`.venv/bin/python -m pytest tests/unit -q`, run against the committed HEAD b2d64da, not against
a working tree). Diffstats below are `git show --stat` on each commit.

| P0 | Commit | What it fixes | Diffstat |
|---|---|---|---|
| R1 | `bc7fe4b` | A moat-blind tick paged nobody — the engine's worst state was log-only | 3 files, +99/-3 |
| E1+V1 | `2862916` | Entity-template query-gen with per-arm receipts; operator personas | 5 files, +272/-13 |
| Q2 | `9276736` | A pack with the wrong currency or broken arithmetic could still be sold — `pack_linter.py` (346 lines) behind a `listing_gate` in `bridge.py` | 6 files, +761/-5 |
| E4 | `f1171f3` | Spend was attributable to a provider but never to a pipeline stage — `telemetry.stage()` + `SPEND BY STAGE` in `costs_report` | 9 files, +231/-24 |
| Q2-fix | `b2d64da` | Q2 made every US pack unlistable: `_render_financial_model` hardcoded `£` | 3 files, +95/-21 |

**The Q2 fail-closed follow-up is CLOSED.** `artifacts.py:274-276` now resolves the symbol per
market — `currency=symbol_for_currency((market_vars or {}).get("currency_hint"))` — from
`config.yaml markets.<code>`, the same table the linter reads. Proof that the two agree is a test,
not an assertion: `tests/unit/test_q2_pack_linter.py:90`
(`test_config_currency_hint_resolves_to_the_symbol_the_linter_expects`) and `:108`
(`test_a_us_render_clears_the_us_currency_check`). Q2+E4 suites alone: 37 passed.

### CI finding — PR #121 was green on the WRONG commit
The 2026-08-06T15:22Z GitHub Actions outage swallowed the `pull_request` events for the last two
commits of `fix/durable-ledger-fence`. Evidence, from `gh run list --branch fix/durable-ledger-fence`:
- `5cacaa17` — `pull_request`, **failure**. Jobs were `guard=success, python=success,
  dotnet=cancelled, nextjs=cancelled`: starvation, not a test failure.
- `751ad7a7` ("ci: re-trigger checks after the … outage") — `workflow_dispatch`, **success**.
- `e9d3a8b` — the PR head, and PR #121's `headRefOid` — **had never been run at all**. Two runs sat
  `queued` for ~11h.

`gh pr checks 121` reports "no checks reported", which reads as "CI not configured" and is actually
"the head commit was never tested". Repo is PUBLIC, so this is not exhausted Actions minutes.
Re-dispatched on the PR head as run `31149441852` → **completed success**: `python=success`,
`dotnet=success`, `nextjs=success`. Caveat, stated rather than glossed: `guard` is
`if: github.event_name == 'pull_request'` (`.github/workflows/ci.yml:20`), so a `workflow_dispatch`
run **skips** it — the protected-files guard has still never run on `e9d3a8b`. It passed on
`5cacaa17`, and `e9d3a8b` deletes nothing, but the clean way to close it is to push any commit to
the PR branch and let the `pull_request` event run all four jobs.

**Rule this produced: `gh pr checks` empty ≠ no CI, and a green run ≠ a green head. Compare the
green run's `headSha` against the PR's `headRefOid`, and check which jobs were `skipped`, before
calling a PR green.**

### Landed
PR #121 **squash-merged** as `e48b512` at 05:19:45Z. That sprang the known squash trap: `e9d3a8b`
is NOT an ancestor of main, so `feat/p0-r1-e1-v1` carried 12 commits, 7 of them content-duplicated
by the squash. Resolved by `git rebase --onto origin/main e9d3a8b`, which was safe to do because
`git diff e9d3a8b origin/main` was **empty** — the squash reproduced the base tree exactly, so the
5 P0 commits replayed with zero conflicts and the post-rebase tree is byte-identical to `b2d64da`.
Re-proved after the rebase: `896 passed, 2 skipped`. Opened as **PR #122** (`5326133 · 886c9d6 ·
dcedae0 · efe034f · df0a0bd`).

### The three P0s that are FIXES vs the three that are EXPERIMENTS
Worth stating plainly, because "SHIPPED" has meant two different things in this programme:
- **Delivered fixes**, live the moment they merge: R1 (moat-blind alerting), Q2 (publish-gate
  linter + currency), E4 (per-stage cost attribution).
- **Experiments still owing a result**: E1 shipped its *harness with the arm OFF* —
  `retrieval.hybrid_entity_checks: []`, and the commit body asserts
  `Retrieval().hybrid_entity_checks == []` to lock the control baseline. So the code that would
  address the 771:145 unverifiable:supported starvation on `payer_solvency` is dark until someone
  populates that list and runs both arms. E2 has a baseline only (§8). E3 has no result.

### E3 — the methodology, recovered (so the next session does not re-derive it)
There is **no probe script**; the 2026-07-31 run was ad-hoc, and its numbers survive only as a
comment at `config.yaml:127-131`:

| N | result | p50 | max | throughput |
|---|---|---|---|---|
| 1 (at rest) | baseline | 8.9s | — | 1x |
| 8 | 8/8 ok | 9.2s | 15.5s | 5.3x — latency essentially flat |
| 14 | 14/14 ok | 13.1s | 34.7s | 6.0x — p50 +42% to buy +13% |

- **The knob is the env var, not the config key**: `PROSPECTOR_CLAUDE_CONCURRENCY`
  (`claude_cli.py:46`, and `:57-60` — "if set, pins the value and wins"). `config.yaml:150`
  `claude_concurrency: 4` is the ambient setting; `cli_governor.py` holds the machine-wide ceiling
  with `fcntl` flock slot files, which is what makes raising N safe rather than multiplicative
  across checkouts.
- **A "collision" has a precise meaning** (`claude_cli.py:145-149`): Claude Code derives its
  per-project session slug from the **cwd path**, so concurrent `claude -p` in a shared directory
  clobber each other's session state and degrade to non-JSON meta output. Proven 2026-07-02:
  concurrency=2 → 0/3 candidates, serialized → 2/3. Note the tension with cache warmth — a
  mkdtemp-per-call fix cost $412.19 of pure cache_write in one day (`claude_cli.py:150-153`), so
  the probe must not "fix" collisions by randomising cwd.
- **Latency is already instrumented**: `telemetry.track_latency` (`telemetry.py:88`) emits
  `latency_ms` per operation; `report.costs_report` (`report.py:289-424`) aggregates it. p50 is
  computed post-hoc from the audit log — nothing new needs building to measure, only to drive N.

### R2 — a raised grounding outage walked around the 3-strike rail and killed the daemon (2026-08-07)

**Mechanism (this part holds).** `_infra_abort_check` (`run.py:61`) is a correct 3-strike rail, but
it is fed *only* by dossiers a vet RETURNED. A vet that RAISES `GroundingInfrastructureError`
returns nothing, so it never reached the rail: `run.py:845` re-raised unconditionally on first
sight → `scheduler/run_scheduled.py:892` → `sys.exit(1)` → launchd `KeepAlive` relaunch.

**⚠️ The SEVERITY claim did not survive measurement — twice.** The premise entering this work was
"seven daemon deaths in fourteen minutes", read off the **pid column of
`store/scheduler/audit/*.jsonl`**. I reproduced that count (8 distinct pids in the 00:00 hour of
2026-08-07) and wrote it up before attributing it. Both readings are wrong: **audit-log pids are
not daemon-restart counts** — any process writing audit rows appears there (CLI runs, control
centre, pytest). Confirmed live: pids 89119 and 90803 appear in the 05:00 hour while daemon pid
49515 was continuously up (`ps` elapsed 05:55:25).

The attributable signature is a tick row in `store/scheduler/ticks.jsonl` whose **top-level**
`error` contains `GroundingInfrastructureError`, because `run_scheduled.py` writes the tick and
*then* exits. Across **195 real (non-dry-run) ticks, 2026-08-01..07**:

| where the error appeared | count | daemon exited? |
|---|---|---|
| top-level `tick["error"]` | **1** (2026-08-06T21:58:21) | yes — `sys.exit(1)` |
| nested in `tick["result"]["resumed"]` | 1 (2026-08-07T02:52) | **no** — caught downstream |

**Actual cost of the one real halt:** next real tick 2026-08-07T00:15:01 → a 2.28 h gap against a
2.00 h configured interval = **17 minutes** of lost generation, plus ~7 wasted process launches.

The 00:00-hour pid churn is real but has a *different* cause: seven short-lived pids each emitting
1-2 `search` rows over ~15 s at ~2-minute intervals — launchd relaunching and
`_startup_grounding_check` correctly refusing to start on a cheap probe. That is the **designed**
behaviour, not this bug.

**Also refuted: my own arithmetic.** I computed "ddg fails 0.83% per search (25/3014) → at ~200
searches/batch, P(≥1 full-chain collapse) = 81%". That model assumes every ddg miss collapses the
whole chain, i.e. that tier 3 always fails too. One halt in ~70 real ticks refutes it: exa was
consulted only 29 times (≈ the 25 ddg failures), and `claude_cli` usually *succeeded*.
**Do not reuse the 81% figure.** The per-provider counts themselves stand:

| provider | calls | failed | rate |
|---|---|---|---|
| ddg (tier 1) | 3014 | 25 | 0.83% |
| exa (tier 2) | 29 | 28 | 96.6% — DNS flap on `api.exa.ai`; it resolves fine now, so this was transient |

**Verdict on priority:** the fix is right — a design where one tail-query failure can exit the
daemon is wrong on its face, and its blast radius is unbounded if grounding degrades for longer.
But it is a **latent-risk fix worth ~17 minutes of measured loss**, not the cause of the 0-PASS
run, and it should not be sequenced ahead of E1/E2/E3 on the strength of the original framing.

**Fix.** `_infra_exception_action(streak, threshold)` (`run.py:76`) routes the raise through the
*same* counter as the returned defers: `continue` below threshold, `halt` at/above it (cancel
un-started vets, then raise **after** the completion loop drains so in-flight vets still
`store.save` themselves), and `raise` when `threshold == 0` — a disabled brake must not be quieter
than no brake. The spend rails are untouched: `_startup_grounding_check` still refuses to start on
a cheap probe, and the daily cap is unmoved.

**Receipts.** `875 passed, 2 skipped in 31.74s` (`.venv/bin/python -m pytest tests/unit -q`), up
from 866 — six new tests in `tests/unit/test_grounding_outage_does_not_kill_daemon.py` plus nine
in `test_infra_abort_streak.py`. **Non-vacuity was bisected, not assumed:** with only the old
`except GroundingInfrastructureError: raise` reinstated, exactly the three loop-level regression
tests fail (`test_one_grounding_outage_does_not_kill_the_batch`,
`test_two_consecutive_outages_still_do_not_kill_the_batch`,
`test_many_scattered_outages_below_the_threshold_never_halt`); the guard tests pass both ways by
design. The wiring tests drive the real `run_signal` loop, because the wiring — not the policy —
was the bug.

**A flaky test of my own making, and why the obvious test is impossible here.** The first version
of the reset test alternated outage/success through the real loop. It passed five runs, then
failed. Cause: the streak advances in `as_completed` order, and `as_completed` yields futures that
were *already finished* when it was first called out of a **set**, i.e. in arbitrary order — even
with a single worker, where execution order is fixed. So no submission pattern with ≥3 collapses
can be guaranteed not to present 3 consecutively. The loop-level file now asserts only
order-INDEPENDENT properties; the streak-RESET property is pinned deterministically at policy level
(`test_infra_abort_streak.py::test_a_healthy_verdict_resets_the_streak_before_a_raise`). Stability
re-checked: 10 consecutive randomized runs, 29 passed each.

**Known, accepted limitation (not silently dropped).** On the `continue` path the candidate that
hit the outage produces no dossier and is not banked for `vet --resume`. It is a freshly generated
in-flight candidate, so nothing already paid for is lost, and it is strictly better than the old
path, which lost it *and* killed the daemon. Banking it would need a new gate string, and
`dossier.py:46` decides DEFER-vs-KILL from a hardcoded `(DEFER_GATE, "moat_exhausted")` membership
test — a new gate missing from that line would be scored a KILL, i.e. a candidate killed by our own
outage.

**Still unproven, deliberately not claimed.** That this halt was the whole reason for the 0-PASS
run: the 19:55 tick had healthy retrieval and still killed all 15. That remains open.

### Still open
- **E1 the experiment** (populate `hybrid_entity_checks: [payer_solvency, distribution]`, run both
  arms, compute per-arm unverifiable rate offline from `CheckResult.query_source`). This is the
  cheapest of the three: the harness and the offline A/B path already exist.
- **E2** (bias 2-3 batches toward the operator/B2B personas added by `886c9d6`, then PASS-rate
  delta by persona class against §8's baseline).
- **E3** (N=4/6/8 via the env var, then one clean k=15 tick at the knee).
- All three need the daemon quiet. `store/scheduler/PAUSE_GENERATION` is the half-stop
  (`run_scheduled.py:407-409`, a plain file-existence check; the drain keeps running).
  **Engage it at the START of the measurement session and delete it at the end** — a pause file
  left behind for an experiment nobody is running is the same failure mode as the backlog cap that
  suppressed generation for six weeks.
