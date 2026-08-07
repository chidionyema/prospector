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

## 17. E11 RESULT — confidence-floor calibration (2026-08-07, offline, zero LLM)

Script: `tools/experiments/e11_confidence_floor.py` (re-runnable, read-only over `store/dossiers/*.kill.json`).
It drives the **real** `prospector.kill_filter.apply_gates` per lane via `cfg.for_lane(tier)`,
not a reimplementation, and only mutates `thresholds.confidence_floor`.

**Methodology correction, stated because the first pass got it wrong.** An initial run reported
"74.6% of kills do not reproduce at floor 0.0", which is an artefact, not a finding: `apply_gates`
only fires the per-check hard gates, so kills recorded as `min_composite` (607), `moat_ungrounded`
(171), `adversarial_decisive` (142) and `source_or_die` (24) fire *downstream* and can never
reproduce in this replay. The honest denominator is the **333 kills whose gate reproduces under the
shipped config** — the only population `confidence_floor` can move. 187 of the 333 were ruled by a
brain still on the moat today.

| floor | still KILL | freed to scoring | % of the 333 |
|---|---|---|---|
| 0.0 (shipped, inert) | 333 | 0 | 0.0% |
| 0.3 | 292 | 41 | 12.3% |
| **0.4** | **267** | **66** | **19.8%** |
| 0.5 | 189 | 144 | 43.2% |
| 0.6 | 146 | 187 | 56.2% |
| 0.7 | 60 | 273 | 82.0% |

Confidence of the firing check (n=333): p10 0.23, p25 0.40, **median 0.55**, p75 0.65, p90 0.70.
Freed at 0.4, by gate: `incumbency=31, value_durability=16, payer_solvency=7, legality=6,
pain_reality=3`. At 0.5: `incumbency=66, value_durability=29, payer_solvency=17`.

**Reading.** The freed kills concentrate in exactly the two gates the 2026-06-15 war room flagged
for over-restriction (`kill_filter.py:47-50` cites it: known-good theses killed at conf 0.25 while
the gate had already computed the signal). A floor of **0.4 is the defensible calibration** — it
retires the bottom quartile of grounded kills (66 candidates, 19.8%) without touching the median
kill at 0.55; those candidates fall through to scoring, where a low composite and the adversarial
gate still stop them publishing, so this loosens *killing*, never *publishing*. 0.5+ frees ~43%+
and is a product decision, not a calibration. NOT YET APPLIED — `confidence_floor` is still 0.0
pending founder sign-off, because it widens what survives into the catalogue funnel.

**Second finding, config-era drift.** 34 recorded per-check kills do NOT reproduce under today's
config (`incumbency` 22, `value_durability` 9, `legality` 2, `payer_solvency` 1) — they were ruled
under superseded gate configurations. Consistent with §10's provider-era confound: kill-rate
comparisons across eras are measuring config changes as well as ideas.

### §9 legality-polarity HYPOTHESIS — CLOSED (was: "check the claim text")
Confirmed real, and **already fixed in the shipped config**; what remained was a comment telling
the next reader to re-introduce it. Both dossiers fired `legality=supported` on a rationale saying
the activity is lawful — `459b72f3630d21be` ("heirloom tomatoes are completely legal to grow, sell,
buy, and eat anywhere in the United States", conf 0.43) and `7e603974bcde1e09` ("basic gardening
work does not require a specific licence", conf 0.42). Both were killed for being legal. Today
`config.yaml:224` reads `legality: [refuted]` at every lane, matching the positive-polarity
doctrine at `:210-214`, and neither kill reproduces. But `:215-219` still carried a stale paragraph
ending "hence legality kills on `supported`" — the code was right and the comment argued for the
bug. Replaced with the history plus the two receipts and a "do NOT fix this back" line. Not a
behaviour change; a change to the thing that would have caused the next regression.

## 18. The grounding bottleneck is RELEVANCE, not availability (2026-08-07, offline, zero LLM)

This section replaces the standing "the 19:55 tick had healthy retrieval and still killed all 15"
lead. That framing is retired: the premise was partly wrong, and the corrected version points at a
bigger, cheaper lever.

### 18.1 The premise, corrected

There is no 19:55 tick. `store/scheduler/ticks.jsonl` has 2,087 rows, 874 of them allowed and
non-dry, and none carries a 19:55 timestamp. Reconstructing batches from `created_at` clustering
over `store/dossiers/*.json` (gap > 20 min starts a new batch), the nearest evening batch on
2026-08-06 is **19:38:41, n=8** — not 15 — and its kills are NOT one systemic cause:

    min_composite 3, moat_ungrounded 3, source_or_die 2

So 5 of 8 died on grounding-QUALITY gates. "Healthy retrieval" was true at the probe level and
false at the passage level, and that distinction is the whole finding.

Also confirmed while measuring, so nobody re-derives them:
- The R2 grounding halt is **exactly one row** in the whole file: `2026-08-06T21:58:21`,
  `err=GroundingInfrastructureError: ALL grounding providers dead`. The measured severity in §16
  (1 halt / 195 real ticks / 17 min) stands.
- The rate gate is **live and firing in production**: `2026-08-07T02:52:58` logged
  "grounding degraded: the retrieval probe did not answer within 45s — generating now would mint
  DEFER rows rather than verdicts, so this tick only drains". The rule works as designed.
- Tick rows carry an EMPTY `result` object in every row measured. E4 stage telemetry landed on
  `main` and only reached the daemon's checkout with the merge below, so tick-level outcome
  attribution starts from now, not retroactively.

### 18.2 The actual bottleneck

Across 473 August dossiers, `moat_ungrounded` fired 117 times — the second-largest gate after
`min_composite` (119), and combined with `source_or_die` (14) that is **131 of 366 August kills
(35.8%) lost to grounding quality rather than idea quality**.

The decisive measurement: those 117 dossiers carry a **mean of 21.4 citations each, and ZERO of
them have zero citations**. Retrieval fetched documents every time. The checks still ruled
`unverifiable` (320 unverifiable vs 218 supported vs 2 refuted across their checks). The engine is
not starved of sources; it is starved of sources that ANSWER THE QUESTION ASKED.

Per-check grounding yield, all August dossiers (`verdict` distribution, mean citations per check).
**This table is a snapshot of a MOVING store — do not quote it, re-run it.** The daemon writes new
dossiers continuously, so the figures drift within minutes (re-run 20 minutes later: kills
366 -> 371, grounding share 35.8% -> 35.3%, incumbency 55.0% -> 54.8%). The authority is
`.venv/bin/python tools/experiments/e12_grounding_yield.py`, which prints this table, the gate
mix, the zero-citation count and the E1 eligibility check, and writes
`e12_grounding_yield_receipts.json`. The RANKING is what is stable, not the decimals.

| check | n | unverifiable | supported | refuted | mean cites | mean conf |
|---|---|---|---|---|---|---|
| payer_solvency | 311 | **60.5%** | 30.5% | 9.0% | 4.3 | 0.56 |
| incumbency | 229 | **55.0%** | 17.0% | 27.9% | 4.9 | 0.62 |
| legality | 305 | **54.8%** | 42.6% | 2.6% | 4.7 | 0.57 |
| value_durability | 290 | 48.3% | 40.7% | 11.0% | 3.9 | 0.51 |
| pain_reality | 237 | 40.5% | 57.8% | 1.7% | 4.2 | 0.57 |
| distribution | 288 | 37.5% | 61.5% | 1.0% | 4.4 | 0.58 |
| claims_verifiable | 104 | 35.6% | 55.8% | 8.7% | 4.9 | 0.61 |
| buyer_intent | 209 | 33.0% | 67.0% | 0.0% | 4.2 | 0.56 |
| route_to_market | 80 | 32.5% | 61.2% | 6.2% | 4.1 | 0.53 |
| currency | 129 | 28.7% | 66.7% | 4.7% | 4.7 | 0.59 |

Every check retrieves ~4-5 citations. The spread from 28.7% to 60.5% unverifiable is therefore
NOT a retrieval-volume effect. It is query targeting.

### 18.3 What this changes about E1

E1's arm list is half right and cannot be fixed by config alone.

- **`payer_solvency` is the correct target** — the worst check in the engine at 60.5%
  unverifiable, and the entity template ("{payer} budget spending on {base}") attacks exactly the
  failure mode.
- **`distribution` is the wrong second target.** At 37.5% it is the fifth-BEST check of ten. The
  headroom is small and the measurement will be noisy.
- **The two checks that deserve the arm — `incumbency` (55.0%) and `legality` (54.8%) — cannot
  receive it today.** `_ENTITY_TEMPLATES` (`prospector/verify.py:223-232`) has exactly two keys,
  `payer_solvency` and `distribution`. `_entity_queries` returns `[]` for any other check
  (`verify.py:241-243`) and the caller silently falls through to the LLM chain
  (`verify.py:478-483`).

  **TRAP: `retrieval.hybrid_entity_checks` looks like a general switch and is not.** Listing
  `incumbency` or `legality` there is INERT — no error, no log, the arm simply never engages and
  the experiment reads as "no effect". Extending `_ENTITY_TEMPLATES` is a code change, and it is
  the natural E1 follow-on.

### 18.4 A limit on E1's measurement plan

The plan recorded earlier ("compute per-arm unverifiable rate offline from
`CheckResult.query_source`") works **forward only**. `query_source` exists and is populated
(`models.py:213`; set at `verify.py:481-493`, persisted at `:527/:534/:553/:561`), but no August
dossier carries the field, because the code reached the daemon's checkout only with today's merge.
There is no retroactive control arm. Both arms must be run fresh.

### 18.5 Deployment — P0 is now actually live

The standing blocker ("merging PR #122 to main did not make P0 live, because the daemon's launchd
`WorkingDirectory` is the checkout on `fix/durable-ledger-fence`") is CLOSED.

The "~27 conflicting source files" estimate was wrong. Measured with
`git merge-tree --write-tree origin/main HEAD`: **exactly two files conflict**,
`prospector/decay.py` and `prospector/scheduler/alerts.py`, and both conflicts are additive rather
than semantic. Resolved per-hunk so each file keeps the other side's auto-merged changes:

- `decay.py` kept HEAD — a strict superset: the same `logger.info` plus `_queue_unlist()` and the
  CRITICAL "LIVE PACK KILLED ON RE-VET, still sellable" alert. Taking main's side would have
  re-opened the money-rail gap where a re-vetted KILL keeps selling.
- `alerts.py` kept origin/main — the superset: `TELEGRAM_KEYS` gains `moat_blind`.

Receipts: merge commit `190cd00`, **920 passed / 3 skipped** on the merged tree (up from 875 on the
branch alone), POPDD gate PASS (1725 python-lane tests). Fast-forwarded into the daemon's checkout
and pushed. Daemon restarted onto it: pid 49515 -> 19735, cwd
`/Users/chidionyema/Documents/code/prospector`. `hybrid_entity_checks`, `moat_blind`,
`_queue_unlist` and `_infra_exception_action` are all present in the live checkout.

### 18.6 Ranking, revised

`moat_ungrounded` + `source_or_die` = 35.8% of August kills, all of them on candidates that DID
retrieve evidence. That is a larger and cheaper lever than E11's confidence floor (§17: floor 0.4
frees 66 of 333 hard-gate kills) because it does not loosen any gate — it makes the evidence
actually arrive. Query targeting should outrank the floor decision in sequencing.

### 18.7 Daemon-level proof that the merge is actually running

Presence on disk is not deployment. The probe that settles it: re-running E12 twenty minutes after
the restart shows `query_source present on checks: {'llm_batched': 4}`. No August dossier carries
that field at all (§18.4) — it can only have been written by code that reached the checkout with
today's merge. The new daemon (pid 19735) is therefore executing the merged `verify.py`, not the
old image. That is the receipt "P0 is live" needs; the merge commit alone is not.

## 19. Floor applied · the rerank ceiling measured · E1 reordered (2026-08-07, offline, zero LLM)

Founder direction opening this session: *"i need this done yesterday, 2 weeks is unrealistic."*
The §4 estimate was never a statement about the WORK — it is the wall-clock of the *measurements*.
This section separates the two and collapses the measurement half where it can be collapsed.

### 19.1 `confidence_floor` 0.0 -> 0.4 — APPLIED (founder sign-off 2026-08-07)

§17 left this pending; it is now shipped. `config.yaml` global (`thresholds.confidence_floor`) and
both lanes that were still inert (`smb`, `growth`). Note `side_hustle` and `venture` were **already
at 0.4**, so this is harmonisation across lanes, not a novel setting — half the engine has been
running this calibration all along.

Receipt that it is live, not merely edited (`load_config()` -> `cfg.for_lane(t)`):

    global 0.4 · side_hustle 0.4 · smb 0.4 · growth 0.4 · venture 0.4

**Cross-validated by a second, independent method.** §17's figure came from replaying
`kill_filter.apply_gates`. Counting the *recorded* `gate_fired` + firing-check confidence straight
off `store/dossiers/*.kill.json` is a different path to the same population, and the gate mixes
agree to within noise:

| gate | E11 replay (freed at 0.4) | recorded-gate count (conf < 0.4) |
|---|---|---|
| incumbency | 31 | 32 |
| value_durability | 16 | 16 |
| payer_solvency | 7 | 7 |
| legality | 6 | 4 |
| pain_reality | 3 | 3 |
| distribution | — | 1 |
| **total** | **66 / 333** | **63 / 1,323 kill dossiers** |

**It closes §11 hallucination gap 3, which was not the stated goal.** §11 flagged the
"refuted-with-zero-citations edge": `verify.py:377` downgrades an *uncited supported* check to
unverifiable, but no equivalent rail existed for *refuted*. There is now, and it falls out of the
arithmetic rather than needing new code — confidence is recomputed from citations
(`verify.py:70-133`), so a refutation citing nothing scores exactly 0.0 and sits below the floor.
An uncited refutation can no longer hard-kill a candidate.

This surfaced as three test failures (`test_shadow_moat.py`, `test_stochastic_full_vetting.py` x2),
all of which were mocking `"citations": []` and asserting that the resulting kill short-circuited —
i.e. **asserting the unsafe behaviour**. Fixed the fixtures, not the gate, per the instruction
already written at `test_shadow_moat.py:21-31` for this exact fixture class ("make the mock's PASS
genuinely grounded, never relax the gate so the mock's story works"). Added
`test_an_uncited_refutation_does_not_short_circuit_at_the_confidence_floor` to pin the property the
floor bought, with a vacuity guard asserting the floor is non-zero.

**Receipts.** `922 passed, 2 skipped` (`.venv/bin/python -m pytest tests/unit -q`), up from 920 on
the merge. **Non-vacuity bisected, not assumed**: with `config.yaml` stashed back to floor 0.0 the
new test FAILS and the three repaired tests pass, so each one is testing the floor and not the
weather.

**Cost consequence, stated because §17 did not.** Raising the floor makes kill-fast fire less often:
a candidate that used to die on its first refuted check now runs the rest of the order. Measured:
63 of 1,323 historical kills (4.8%) fired a sub-0.4 refuted gate, having run a mean of 2.22 checks —
so roughly 3.8 additional checks each, ~240 extra checks across the entire two-month kill history.
Real, bounded, and small. Not a reason to reconsider; a number to have rather than to discover.

### 19.2 E16 CEILING RESULT — the rerank has partial headroom, and the judge is the bigger half

§14 registers E16 as "bge-rerank the stored passages of bucket-D checks". Running the real reranker
needs a ~2GB local `torch`+`transformers` install (confirmed absent: no `torch`, `transformers`,
`sentence_transformers`, or `FlagEmbedding` in `.venv`; Ollama is present with gemma3/llama3.2).
Before buying the tool, measure whether there is anything for it to find.

Script: `tools/experiments/e16_rerank_ceiling.py` (read-only, zero LLM, zero network; `--current-moat`
restricts to `claude_cli`/`claude` per §10's provider-era confound). It scores every stored passage
by overlap with the **candidate-specific** query vocabulary — template boilerplate from
`_DISCONFIRM_TEMPLATES`/`_CONFIRM_TEMPLATES` is stripped first, since it is byte-identical across
every candidate and would inflate every set equally. Then, stratified by `check_name` so no easy
check is compared against a hard one, it asks: does a bucket-D check already hold a passage as
query-relevant as the MEDIAN best passage of that same check's *supported* rulings?

Population: **4,500 bucket-D checks** (unverifiable, passages stored, no infra failure) over 24,329
scored passages; 738 checks / 5,673 passages on the current moat alone.

| scope | checks | reachable | best passage NOT already rank 0 | junk share |
|---|---|---|---|---|
| all provider eras | 4,500 | **37.9%** | 45.5% | 4.8% |
| current moat only | 738 | **40.8%** | 47.4% | 3.4% |

Per-check reachability is strikingly flat (22.6%–44.8%), which is itself informative: this is not a
property of one badly-templated check, it is uniform across the engine.

**Three readings, in order of how much they change the plan.**

1. **Reranking has real but partial headroom.** ~38–41% of bucket-D checks already hold a passage
   as query-relevant as what actually sufficed to rule elsewhere. Combined with §18's 35.8% of
   August kills lost to grounding quality, that is roughly **14% of all kills recoverable from
   evidence already on disk and already paid for** — no new retrieval, no new tokens.
2. **The judge is the bigger half, and this is the finding that reorders E1.** In **54.5%** of
   bucket-D checks the most query-relevant passage was **already at rank 0** — the judge saw the
   best available passage first and still ruled unverifiable. A reranker cannot help those. That is
   direct support for §10's R1 ("the question class is unanswerable in principle") and for the E13
   claim reframe over any retrieval-side fix, and it is consistent from the other direction with
   §18's finding that grounding fails on relevance at ~4-5 citations per check.
3. **Junk is NOT the story, and my first read of it was wrong.** A hand-inspected bucket-D sample
   showed a UK employment-tribunal check grounded on zhihu.com homepage boilerplate in Chinese, and
   the obvious inference was that the corpus is full of garbage. Measured: junk is **4.8%** of all
   stored passages (1,100 stubs, 53 non-Latin, 6 nav-chrome out of 24,329). The anecdote was real
   and the generalisation from it was false. Recorded here because that inference was one script
   away from becoming a work item.

**Caveat, load-bearing.** Lexical overlap is a PROXY for probativeness. A passage can share query
vocabulary and still not answer the question — so 37.9% is an **upper bound** on rerank headroom,
not a prediction of yield. The probe's job is to decide whether the 2GB install is worth making
(it is: an upper bound of ~14% of all kills clears any reasonable bar) and to rank E13 above E16
(it does, on the rank-0 result). It is not a substitute for running the reranker.

### 19.3 `ffecc4c` — CLOSED, after three sessions of being carried as an open question

It was never missing. `ffecc4c` and `a447e4f` have the **identical patch-id**
(`2e3786251e069c66f63a0343d13f2ebe3fca3c52`) and an empty tree-diff: the commit was replayed under
a new hash by the §16 `git rebase --onto origin/main e9d3a8b`. `a447e4f` is on `HEAD`
(`fix/durable-ledger-fence`) and reaches main through PR #123. `ffecc4c` itself is unreachable from
any ref, which is why it kept reading as lost.

**Rule this produced: a dangling commit hash is not evidence of lost work — compare patch-ids
before hunting for the content.** `git show <sha> | git patch-id --stable` costs nothing and
answers it outright.

### 19.4 What this does to §4's sequencing

The reordering is driven by the rank-0 result, not by preference:

1. **E13 claim reframe** (§10) — primary. Addresses the ~55% of bucket-D where the best passage was
   already on top, which no retrieval-side change can touch. Replayable offline on stored passages.
2. **E16 rerank** (§14) — secondary, ~38% upper bound, now justified enough to pay the 2GB install.
3. **E1 entity templates** — still worth shipping (it improves the queries feeding BOTH of the
   above), but it is no longer the head of the queue. `_ENTITY_TEMPLATES` (`verify.py:223-232`)
   still needs extending to `incumbency`/`legality` per §18.3; that remains a code change.

The measurement half of §4 collapses because E13/E16/E15/E17 all replay data already on disk.
What does NOT collapse: E2 (needs biased live batches) and E3 (needs live concurrency probing).
Those two are genuinely wall-clock-bound and no reframing changes that.

## 20. Q4 citation source quality - what our ruled verdicts actually rest on (2026-08-07, offline, zero LLM)

### 20.1 The measurement

Motivation to state: the founder observed `gitnux.org` (an AI-generated statistics farm) used as a kill-log citation, and a raw `youtube.com/watch` link used as evidence. The instinct is a domain denylist in the grounding path. §18 says do not act on that instinct blind: grounding already fails on RELEVANCE not availability, so deleting domains can only starve checks further. So this measures the blast radius BEFORE any policy exists.

Script: `tools/experiments/q4_citation_source_quality.py` (read-only, zero LLM, zero network, runs off dossiers already on disk). Receipts: `tools/experiments/q4_citation_source_quality_receipts.json` and `tools/experiments/q4_citation_source_quality_receipts_current_moat.json`.

**METHOD CORRECTION** worth recording (this is a trap that would have produced a wrong answer): `check["citations"]` holds `source_id` hashes, NOT urls. The urls live in `check["sources"]`. Counting `sources` measures what retrieval FETCHED; resolving the ids against `sources` measures what the judge actually LEANED ON. Those are different populations and only the second can justify a denylist. Fetched corpus: 46,992 urls across 10,933 distinct domains. Cited evidence behind ruled verdicts: 8,842 urls.

Population: 1,558 dossiers carrying checks. 2,586 ruled (supported or refuted) checks across all provider eras, 1,234 on the current moat. 8,842 resolved citation urls all eras, 4,894 current moat. 6 ruled-but-uncited checks. 0 unresolved citation ids.

| tier | all eras | share | current moat | share |
|---|---|---|---|---|
| other | 6,752 | 76.4% | 3,677 | 75.1% |
| government | 954 | 10.8% | 564 | 11.5% |
| ugc_social (LOW) | 708 | 8.0% | 402 | 8.2% |
| established_org | 177 | 2.0% | 109 | 2.2% |
| media | 117 | 1.3% | 71 | 1.5% |
| academic | 74 | 0.8% | 28 | 0.6% |
| wikipedia | 42 | 0.5% | 28 | 0.6% |
| stats_farm (LOW) | 18 | 0.2% | 15 | 0.3% |

The two policy numbers:

- exposure (ruled checks citing at least one low-quality domain): 485 / 2,580 = 18.8% all eras; 276 / 1,228 = 22.5% current moat.
- blast radius (ruled checks resting ONLY on low-quality domains - the verdicts a denylist would demote to `unverifiable`): 52 / 2,580 = 2.0% all eras; 17 / 1,228 = 1.4% current moat.

**Reading.** The evidence base is materially dirtier than expected (nearly a fifth to a quarter of ruled checks touch a low-quality source) but the cost of cleaning it is small, because low-quality sources are almost always accompanied by a better one. §18's fear that a denylist would starve checks is now quantified and it is small.

| domain | tier | count |
|---|---|---|
| facebook.com | ugc_social | 301 |
| reddit.com | ugc_social | 95 |
| youtube.com | ugc_social | 75 |
| tiktok.com | ugc_social | 70 |
| linkedin.com | ugc_social | 66 |
| instagram.com | ugc_social | 45 |
| mumsnet.com | ugc_social | 25 |
| pinterest.com | ugc_social | 12 |
| quora.com | ugc_social | 9 |
| uk.linkedin.com | ugc_social | 8 |
| gitnux.org | stats_farm | 7 |
| worldmetrics.org | stats_farm | 5 |
| wifitalents.com | stats_farm | 4 |
| zipdo.co | stats_farm | 2 |
| nextdoor.co.uk | ugc_social | 1 |
| x.com | ugc_social | 1 |

Two facts to call out.

**(a) concentration.** facebook.com, reddit.com, youtube.com and tiktok.com together carry 541 of 708 ugc_social citations = 76.4%, so a very short list reaches most of the problem.

**(b) The founder observed gitnux.org twice.** The true count is 7 citations, and the whole stats_farm tier is 18 citations = 0.20% of cited evidence - real, cheap to remove, and NOT the bulk of the problem.

### 20.2 UGC is not uniformly unprobative - the finding that shapes the policy

The per-check split is the point.

| check | ruled | exposed | exposed share | only-low |
|---|---|---|---|---|
| route_to_market | 82 | 45 | 54.9% | 8 |
| distribution | 359 | 136 | 37.9% | 26 |
| buyer_intent | 200 | 48 | 24.0% | 2 |
| pain_reality | 336 | 70 | 20.8% | 4 |
| payer_solvency | 263 | 45 | 17.1% | 5 |
| value_durability | 457 | 48 | 10.5% | 4 |
| incumbency | 325 | 31 | 9.5% | 0 |
| legality | 312 | 25 | 8.0% | 3 |
| currency | 148 | 22 | - | 0 |
| claims_verifiable | 104 | 15 | - | 0 |

Argue this: exposure concentrates in the two channel checks. That is not contamination, it is the evidence being the right shape for the question. For `distribution` and `route_to_market` a Facebook group with a large membership IS the channel being evidenced. For `legality` or `payer_solvency` a TikTok cannot establish what the law says or what buyers pay. So admissibility must be scored per check, not per domain. A blanket denylist would destroy most of its evidence precisely where that evidence was valid.

### 20.3 Policy simulation - three candidate policies, measured not asserted

Policies simulated in the same script. UGC treated as admissible for these four checks only: distribution, route_to_market, buyer_intent, pain_reality.

| policy | ruled verdicts demoted, all eras | share | current moat | share |
|---|---|---|---|---|
| P0_global (deny ugc_social + reference_noise + stats_farm everywhere) | 52 | 2.02% | 17 | 1.38% |
| P1_check_aware (deny stats_farm + reference_noise everywhere; deny ugc_social only on checks where it cannot be probative) | 12 | 0.47% | 1 | 0.08% |
| P2_farm_only (deny stats_farm + reference_noise only) | 0 | 0.00% | 0 | 0.00% |

P0's damage by check: distribution 26, route_to_market 8, payer_solvency 5. P1's damage by check: payer_solvency 5, value_durability 4, legality 3.

Kill gates that would be disturbed by the only-low checks, all eras: min_composite 24, moat_ungrounded 12, none-recorded 10, source_or_die 3, legality 1, adversarial_decisive 1, payer_solvency 1.

**Recommendation.**

1. Ship P2 immediately. It costs literally zero ruled verdicts in two months of history and removes AI-generated statistics farms and dictionary/thesaurus chrome from the evidence base. There is no argument against a free change.
2. Then P1. It costs 12 ruled verdicts across all history (0.47%), one on the current moat, and removes the 18.8% exposure. P0 costs 4.3x more than P1 to remove evidence that was arguably valid, and it pays that cost precisely in the checks where UGC was the right source. Do not ship P0.
3. Implement it as **ADMISSIBILITY AT RULING TIME**, not as removal from the retrieval fetch. §18 showed grounding is relevance-bound, so shrinking the fetched pool is the one thing that cannot help. Admissibility leaves retrieval untouched and only stops a low-quality domain being the SOLE basis of a ruling.

**Caveat, load-bearing.** The tier lists are hand-declared and evidence-led rather than exhaustive, and the `other` tier is 76.4% of cited evidence and is unaudited. This measurement bounds the user-generated-content and statistics-farm question only. It is not a general verdict on source quality, and a domain sitting in `other` is not thereby endorsed.

### 20.4 Editorial risk item - founder's call, deliberately not changed

Real, sourced, sensitive content is live in the catalogue: a tattoo-trade dossier citing two suicides, and targeting language aimed at low-income carers. It is grounded and true. Silently editing it would violate the project's own source-or-die and no-overclaim ethos, and quietly removing true sourced material is the same class of error as shipping unsourced material. It is therefore flagged for an explicit editorial decision by the founder and has deliberately NOT been changed by any agent. Record that no code change is proposed here.

## 21. Subscription auth precedence + Q4 SHIPPED as an admissibility gate (2026-08-07)

### 21.1 The auth bug: an ambient API key outranked the claude.ai subscription

Founder report: `claude -p` returned *"Credit balance is too low"* even though the claude.ai login is live.

**Root cause, proven.** `~/.zshrc:54` sources `~/.config/llm/secrets.sh`, which `export`ed `ANTHROPIC_API_KEY`. The Claude CLI's credential precedence puts an ambient API key ABOVE the OAuth subscription login, so every `claude` invocation billed a dead API account instead of the subscription. Grepping the rc files for the variable name finds nothing — the rc file sources a file that sets it, which is why this survived earlier searches.

**The key is valid and broke, which is why the failure reads as a login problem.** `GET /v1/models` → HTTP 200 (the key authenticates) while `POST /v1/messages` → `invalid_request_error: "Your credit balance is too low"`. A `/models` probe therefore proves the key, never the balance.

**Fix (two layers).**

1. **Interactive shell** — `~/.config/llm/secrets.sh:24` dropped `export` (backup: `secrets.sh.bak-2026-08-07`). The value is still readable in-shell and still opt-in per command (`ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" some-tool`), but is no longer inherited by child processes, so `claude` falls through to the subscription. The other five keys (GEMINI/DEEPSEEK/MINIMAX/OPENROUTER/EXA) and the R2 vars are still exported — blast radius was measured across prospector, Hermes and `~/.claude` first: every consumer either strips the var already or uses it as a boolean, so removing the ambient export costs no capability. The engine still gets the key from disk via `_load_dotenv()`.
2. **The engine** — `prospector/cli_auth.py` (new) is now the single definition of the child environment for any `claude` spawn. `SUBSCRIPTION_HIJACK_VARS` (`cli_auth.py:57`) = `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, **`ANTHROPIC_BASE_URL`**. `prospector/claude_cli.py:145` calls `subscription_env()` and passes it at the spawn (`claude_cli.py:185`).

`ANTHROPIC_BASE_URL` is the addition that matters beyond billing: the previous inline strip covered only the two key vars. `BASE_URL` repoints the CLI at a *different inference endpoint*, so a leak would let a non-Anthropic model rule a verdict while still reporting itself as provider `claude_cli` — i.e. it would silently defeat `MOAT_PRIMARY` (`operator.py:889`). This is precisely how the pi-bridge substitutes MiniMax for a whole process. Moat integrity, not just cost.

**Matched-control proof** (same shell, same binary, only secrets.sh swapped): new file → `claude -p` = **OK**; the `.bak` sourced back in → **"Credit balance is too low"**.

**Diagnostic**: `python3 -m prospector.cli_auth` prints the ambient state and exits 1 if hijacked.

**Regression fence**: `tests/unit/test_cli_auth.py` (8 tests) — helper units, a behavioural test that monkeypatches `claude_cli.subprocess.run` and asserts no hijack var reaches the child while `PATH` survives, plus two AST structural guards: *no spawn of the claude binary may inherit the environment*, and *the hijack list has exactly one definition*. Both bisected non-vacuous (broken deliberately, test failed, restored).

**Operational note.** A shell (or Claude Code session) started before the change still carries the old exported value in its own environment; the interactive half of the fix takes effect on relaunch. The engine-side strip is unconditional and needs no relaunch.

### 21.2 Q4 shipped: P1_check_aware admissibility at ruling time

§20 recommended it; this section records it as SHIPPED, per the §20.3 recommendation and NOT as a retrieval denylist.

- `prospector/admissibility.py` (new) — the single home for the tier lists, `tier()`, `host_of()`, `inadmissible_tiers()`, `is_ruling_admissible()`, `demotion_reason()`. `tools/experiments/q4_citation_source_quality.py` now imports from here instead of keeping its own copy, so the measurement and the gate cannot drift about what a `stats_farm` is. **Proof the move changed nothing: re-running both arms after the move reproduced both receipts files byte-for-byte** (`diff` clean; all eras P0=52/2.02%, P1=12/0.47%, P2=0; current moat P0=17/1.38%, P1=1/0.08%, P2=0).
- `config.yaml:201` `admissibility.policy: P1_check_aware`, typed by `config.Admissibility` (`config.py:235`) and validated by `_validate_admissibility` (`config.py:249`), which raises `ValueError` on an unknown policy name or unknown key — a silent typo would otherwise disable the gate while reading as configured.
- `verify.py:449-452` — after the verdict is produced, a SUPPORTED/REFUTED ruling whose citations are ALL inadmissible for that check is demoted to `UNVERIFIABLE`, confidence 0.0, with the demotion reason prepended to the rationale and the original rationale preserved for the audit trail.

Three properties held deliberately, each with a test:

1. **A demotion is not an outage.** It must NOT set `retrieval_failed` — that flag means "come back later" and would fire the DEFER gate (`verify.py:693`). The evidence WAS fetched and judged; we are declining to let it be the sole basis of a ruling, which is a finding.
2. **`policy: off` reproduces pre-§20 behaviour exactly**, so the change is reversible by config alone (the project's "deterministic on config" constraint). Asserted as the non-vacuity test.
3. **It is not a pro-candidate lever** — it demotes SUPPORTED rulings on bad evidence exactly as it demotes REFUTED ones.

**Bug found by the new tests, and fixed in the shipped path.** `host_of` was transcribed from `_calc_confidence`'s inline `netloc.replace("www.", "").lower()`, which strips before lowercasing (so `WWW.Reddit.com` fell through to `other` instead of `ugc_social`) and uses an unanchored `replace` (so `notwww.example.com` → `notexample.com`). Corrected to lowercase-then-strip-a-leading-prefix, and `_calc_confidence` (`verify.py:108`) now uses the shared helper — it had been inflating its own domain-diversity term. Neither defect changed the §20 numbers (the corpus is lowercase and has no such host, which is what the byte-identical receipts show), but a classifier that mis-tiers on letter case is not one to build a gate on.

Tests: `tests/unit/test_admissibility.py` (26).

## 22. E6 SHADOW MODE BUILT — local-embedding prescreen prefilter (2026-08-07, offline, zero LLM)

E6 (§3) asks whether a local embedding prefilter can drop ≥20% of LLM prescreen calls at no PASS
loss, and mandates **shadow-mode first (log, don't act)**. The shadow half is now built and OFF by
default. No measurement yet — this section records the mechanism and the blocker, not a result.

**Zero decisions changed, structurally.** `prescreen.prescreen` (`prescreen.py:153`) is now a thin
wrapper: `_decide` (`prescreen.py:176`) holds the ENTIRE three-stage gate and produces the result
tuple, which is returned untouched; `record_shadow` is called afterwards and its return value is
discarded. The prefilter cannot influence a decision even by accident, and `record_shadow`
(`prescreen_prefilter.py:352`) swallows every exception — an observer that can raise inside a
keep-biased gate is a decision change by another name.
Proof: `tests/unit/test_prescreen_prefilter.py::test_prescreen_result_identical_with_shadow_on_and_off`
runs the same five candidates with the flag off and on and asserts `json.dumps(off) == json.dumps(on)`
AND that the operator received the same call sequence, with a non-vacuity assertion that the
prefilter did fire (would_drop) on that run.

**BLOCKER — there is no local dense embedding model on this machine.** Measured 2026-08-07:
`sentence_transformers`, `torch`, `transformers`, `onnxruntime`, `model2vec`, `fastembed` all absent
from `.venv`; `ollama list` carries only chat models (qwen2.5-coder:7b, gemma3:4b/1b, gemma2:2b,
llama3.2). nomic-embed-text-v2 (~274MB) or Qwen3-Embedding-0.6B (~1.5GB) would be a download, which
this task's scope forbade. So the default `backend: lexical` reuses what the repo already has: the
dedup content-word tokeniser (`dedup._content_tokens`) plus character trigrams, L2-normalised, scored
through the ONE cosine already in the tree (`novelty.cosine_similarity`). `backend:
sentence_transformers:<model>` is accepted and degrades to lexical with a log line if the import
fails; every shadow row records `backend_used`, so a mixed log can never attribute lexical numbers to
a dense model. Until a dense model is installed, E6's ≥20% figure is a test of the LEXICAL prefilter
only — that is a floor for the bet, not a refutation of it.

**The score is prequential, so the logged agreement is out-of-sample.** No labelled corpus of
"obvious near-misses" exists on disk, so the prefilter learns from the LLM decisions it shadows: each
candidate is scored against the exemplars accumulated so far (never itself), then its own LLM outcome
is appended. Score = similarity-weighted keep-rate of the k nearest exemplars above `min_similarity`.
Below `min_exemplars` it ABSTAINS — cold start never drops.

Config (`config.yaml`, all defaults inert): `prescreen_prefilter.shadow_mode: false`, `backend:
lexical`, `threshold: 0.35`, `neighbours: 5`, `min_similarity: 0.15`, `min_exemplars: 20`,
`max_exemplars: 500`, `log_dir: ""` (→ `<store.dir>/prescreen_shadow/shadow-YYYY-MM.jsonl`, honouring
`PROSPECTOR_STORE_DIR`; nothing is bound at import time). Unknown keys raise at startup
(`config._validate_prescreen_prefilter`), same rule as `_validate_admissibility` — a `shadow_mod:`
typo must stop the process, not read as configured-on while inert.

Read the metric back with `prescreen_prefilter.summarise_shadow_log(path)`: `llm_calls_saved_pct` is
computed only over rows where the LLM was ACTUALLY called (structural rejects never reach stage 3, so
counting them would inflate the saving), and `false_drop_rate` is the "no PASS loss" side — the share
of LLM-kept candidates the prefilter would have discarded.

**Not built, deliberately:** anything that acts. Turning the prefilter into a gate is a separate
change E6 must earn with measured agreement first.

Tests: `tests/unit/test_prescreen_prefilter.py` (13).

## 23. Wave 1 — R3, R4, S5, E13 (2026-08-07, offline, zero LLM, zero network)

Receipt for the whole wave: `1022 passed, 2 skipped, 19 warnings in 112.20s`
(`PYTHONPATH=<repo> .venv/bin/python -m pytest tests/unit -q`, exit status captured BEFORE any pipe).
Prior baseline was §16's `896 passed, 2 skipped`; the working tree also carries a concurrent
session's uncommitted tests, so the delta is not attributable to this wave alone.
NOTHING IN THIS WAVE IS COMMITTED. `config.py`/`config.yaml` contain another session's hunks.

### 23.1 Three spec claims corrected — the doc was wrong on disk

1. **§2.5 (line ~160) "retrieval.py caching is breaker state, not a persistent result cache" is FALSE.**
   `prospector/retrieval.py:1195` `DiskCache` is content-addressed (sha1 over `query|k|max_chars|market_salt`),
   persists under `store/_cache/` (**15,631 live entries**), is TTL'd, and is wired at `retrieval.py:1428-1431`
   in `make_provider`, gated by `retrieval.cache` / `retrieval.cache_ttl_s` (`config.py:47,52`; `config.yaml:95,96`).
   It survives the writing process — that IS S5's cross-tick property. S5 as specified was already built.
2. **§2.4 "dedup.py already does local embedding work" is FALSE.** `dedup.py:1-15` is stdlib difflib +
   Jaccard. The only `embed()` in the tree is Gemini's (`operator.py:223`) — a network call, and Gemini is
   gone from config. Measured: `sentence_transformers`, `torch`, `transformers`, `onnxruntime`, `model2vec`,
   `fastembed` all `False` from `importlib.util.find_spec`; Ollama holds chat models only.
   **There is no local embedding backend in this repo.** This blocks E6-calibration, V4, L1, E15, E17 on ONE
   decision (E16 hit the same wall independently, §19.2).
3. **§10's 2x kill criterion for E13 is mis-calibrated and should be retired.** It was set against an
   ASSUMED 10:1 absence ratio; measured on disk the ratio is **2.51:1 all-eras, 1.13:1 current moat**.
   With a 46.8% current-moat baseline the arithmetic ceiling — every unverifiable check ruling — is
   **2.13x**. A literal 2x demands recovering 88% of all 236 unverifiable checks. Judge on recovery share.

### 23.2 E13 RESULT — proxy-framed claim reframe

Script `tools/experiments/e13_proxy_claim_reframe.py`; receipts `..._receipts.json` and
`..._receipts_current_moat.json` (both stamp `run_at_utc` + `dossier_files_globbed=1569`, since the
daemon writes dossiers during the run). Read-only over `store/`, `mode=ro` on the db.

Population: 1,458 bucket-D checks / 5,647 passages all-eras; 236 / 901 current moat; plus a 622/208
ruled-check calibration arm. **Recovery share: 27.9% all-eras (407/1458), 29.2% current moat (69/236)**
(payer_solvency 22.8%, distribution 39.6%). Projected grounded-rate 28.5%→47.2% (1.65x) and
46.8%→62.4% (1.33x): **KILLED against §10's 2x, which §23.1(3) shows is unreachable.**

Controls: shuffled-segment control drops to 12.5%/13.5%, so the segment anchor earns ~half the hit rate;
the calibration arm on checks that DID rule sits higher at 38.0%/50.7%. Recorded limitation — the
swapped-detector control on payer_solvency (31.5%) EXCEEDS its own hit rate, so the distribution
"named channel" pattern is the looser of the two detectors.

**The finding that matters, and it corroborates §18 and E16:** the first proxy-matching passage was at
rank 0 for ~47-56% of hits, and **71.7% of hits were passages the judge had ALREADY CITED while still
ruling `unverifiable`.** The evidence was not buried — it was retrieved, cited, and judged non-probative
under the direct claim framing. This is a CLAIM-FRAMING defect, not a retrieval defect. It is also why a
lexical proxy cannot settle it: the LLM-judged replay is the decisive test.

Follow-up cost, sized: **zero new retrieval calls** (passages are on disk). §10's 30-check sample = 30
verdict calls / ~13,950 passage tokens. Full current-moat replay = 236 calls / ~109,761 tokens
(~465/check). Full all-eras = 1,458 calls / ~617,453 tokens. Dollars deliberately not computed — that
needs the spend ledger, which a read-only probe must not touch.

### 23.3 R3 — atomic JSONL appends. tmp+rename REJECTED as destructive

`prospector/jsonl_atomic.py` (new, 318 lines) + `tests/unit/test_jsonl_atomic.py` (352 lines).
Converted: `alerts.emit_alert`/`resolve_alert`, `run_scheduled._append_tick`, `audit.audit`,
`diagnostics.persist_batch_diagnostics`, `decay._queue_unlist`. Tolerant readers:
`run_scheduled._trailing_barren_count`, `_aggregate_ticks`.

**R3 as specified offered "tmp+rename or fsync". tmp+rename is not the weaker option here, it is
destructive**: append-by-rename is read-whole-file → add line → `os.replace`, so every line the live
daemon appended between the read and the rename is silently deleted, and the inode swap orphans a peer's
open `O_APPEND` descriptor. Implemented instead: one `os.open(O_WRONLY|O_APPEND|O_CREAT)` + a SINGLE
`os.write` of the whole payload + `fsync`. POSIX `write()` §2.9.7 requires that be performed with no
intervening modification, so two appenders cannot interleave. A short write (ENOSPC/EINTR) raises
`TornAppendError` and deliberately does NOT retry the remainder — a retry re-seeks to the CURRENT EOF and
could land after a peer's line, turning one torn record into two.

Two calls beyond the literal spec: the reader's tail rule is **positional, not syntactic** (bytes after
the last `\n` are dropped unparsed, because a truncated record can still be valid JSON — `{"n": 9}` is a
prefix of `{"n": 9, "dossiers": 4}` — so the old `json.loads`-per-line readers could return a tick that
was never committed); and `heal=True` prefixes a newline when the last byte is not one, without which a
single torn fragment splices the next record onto itself and poisons every subsequent append.

Receipts: `18 passed in 1.26s`; affected suites `276 passed in 63.46s`. Live trails read clean —
ticks 2253, alerts 1276, batch_diagnostics 93, audit/2026-08-07 2333 rows, all `corrupt=0 torn_tail=0`.
Daemon pid 19735 alive after the run.

### 23.4 R4 — restore drill. FOUND TWO LIVE DATA-LOSS GAPS

`scripts/restore_drill.py` (497 lines) + `tests/unit/test_restore_drill.py` (297 lines). `15 passed in 1.69s`.

**Gap 1 — `store/prospector.db` HAS NO SCHEDULED BACKUP.** `backup_store.py` mirrors
`store/dossiers/*.json` + a gzipped `prospector.jsonl` to R2; `--restore` pulls only dossiers. The db
exists in backup only as ad-hoc migration copies (`.pre-market.bak`, `.pre-tombstone-*.bak`).
**Gap 2 — `backup_store.py:sync` uses `DOSSIER_DIR.glob("*.json")`, NON-RECURSIVE.** The 9 indexed
dossiers under `store/dossiers/quarantine_ungrounded/` (`tombstone='quarantined_ungrounded'`) **have
never been uploaded to R2.** Not reasoned out — the drill's FIRST live run failed with
`[FAIL] index_vs_tree ... 9 rows with NO restored file`, and the failure was correct.
**Neither gap is fixed.** `backup_store.py` was already dirty in the tree; the `rglob` fix and a db
backup artifact remain OPEN and should be treated as P0 — the exposure is silent until a restore is needed.

Live run against the real store, daemon writing concurrently:
```
RESTORE_DRILL PASS checks=12 failures=0
  [PASS] db_integrity     PRAGMA integrity_check -> ok
  [PASS] rows:dossiers    restored=1751 source=1751
  [PASS] dossier_files    restored=1578 source=1578
  [PASS] index_vs_tree    1571 live rows, 180 tombstoned, every live row has a restored file
  orphan_files           7 restored file(s) with no index row   [*.lint.json artifacts, informational]
```
Design: hot `Connection.backup()` snapshot, NOT `shutil.copy` (which under WAL with a live writer can
capture a torn page set). Source opened `file:...?mode=ro` — asserted by a test where an INSERT raises
`OperationalError: readonly`, so the drill cannot lock out the daemon. `_guard_dest()` hard-exits if the
destination resolves inside `store/` or `storage/`. Exit 0 pass / 1 needs-a-human / 2 setup error.
Failure coverage: truncated db, corrupt JSON, missing dossiers, extra rows, and right-filename/
wrong-contents all fail in tests. Deliberately NOT the R2 path: a drill that needs the network cannot
run when the network is what broke.

### 23.5 S5 — the cache existed; it was hardened instead

`prospector/retrieval.py` +112/-16. (1) Atomic `tmp+rename` writes in `_write_entry` — was a bare
`write_text`, a torn-write window with the daemon sharing the dir. NOTE this is the OPPOSITE call from
R3 and correctly so: cache entries are whole-file replacements with a single writer per key, not
appends. (2) Entries carry a `fetched_at` stamp in a v2 envelope; TTL uses `min(fetched_at, mtime)` so a
`store/` restore resetting mtime cannot revive stale grounding. (3) `_read_entry` turns every malformed
shape into a MISS. (4) `cache_dir` was bound at IMPORT (`= CACHE_DIR` in the signature) so monkeypatching
could not redirect it — now resolved in `__init__`. This is the same defect class that polluted the
production audit log and durable ledger. v1 bare-list entries still read; all 15,631 on-disk entries stay valid.

`tests/unit/test_retrieval_cross_tick_cache.py` — 20 tests, `20 passed in 1.48s`; seven affected suites
`70 passed in 11.99s`. **Config keys added: none** — `retrieval.cache` and `retrieval.cache_ttl_s`
(14 days) already existed. Non-pollution PROVEN not asserted: all 15,631 entries in `store/_cache` are
still v1 (`first_char='['`), zero v2 envelopes, so no test wrote there; zero stray `.tmp` files.

**Two S5 sub-clauses deliberately NOT done, both because they cost real money:** putting `provider` in
the key would invalidate all 15,631 entries and LOWER the hit rate (a ddg-cached query re-fetches when
the breaker moves to exa) — the opposite of S5's goal; and normalizing query text re-keys most
LLM-generated queries, flushing the cache, where every flushed key is a live DDG/Exa/claude_cli call.

### 23.6 Defects found but NOT fixed (each is a real open item)

**All six are now CLOSED — see §24 for the fixes and their receipts.** The list is kept as written
because it is the input to §24, and because "found but not fixed" is a status a register has to be
able to record without it becoming permanent.

- `backup_store.py:sync` non-recursive glob — 9 dossiers never backed up (§23.4). **P0.** → §24.2
- No scheduled `prospector.db` backup at all (§23.4). **P0.** → §24.2
- `tools/unlist_killed.py:113` does `QUEUE.write_text("")` to drain `pending_unlist.jsonl` — a
  lost-update race against `decay._queue_unlist` appending. Same defect class as R3, different file. → §24.1
- `decay.py:65-67` binds cwd-relative `LISTINGS_DIR`/`PENDING_UNLIST` at import — the pollution hazard
  the test fence exists for. Not made injectable; out of R3's scope. → §24.3
- `tests/` requires `PYTHONPATH=<repo>`: `.venv/bin/pytest tests/...` alone dies at `tests/conftest.py:5`
  with `ModuleNotFoundError: No module named 'prospector'`. The package is not installed into `.venv`. → §24.4
- No `ruff` in `.venv` (`.venv/bin/ruff` absent) — no lint receipt is obtainable for any of this. → §24.5

### 23.7 Register corrections

Already DONE, wrongly carried as open: **Q2** (`9276736` + fix `b2d64da`, §16), **E12**
(`tools/experiments/e12_grounding_yield.py` + receipts), **E16** (`e0f6991`, §19.2). With R1, R2
(`770a5a5`), E4, V1, E11 and Q4 also landed, the real open backlog is ~33 items, not 38.

## 25. Q4 on the SELLING catalogue — what the shipped gate reaches, and what it leaves (2026-08-07)

§20 measured citation source quality across the whole dossier corpus; §21.2 shipped
`P1_check_aware` admissibility. Both are corpus-wide, and the corpus is overwhelmingly kills. This
section measures the population that decides what a customer receives: **the products currently on
sale.** Probe: `tools/experiments/q4b_live_catalogue_exposure.py` (read-only, zero LLM, one HTTP
GET), tiering through `prospector.admissibility` so it cannot drift from the shipped gate.

### 25.1 Getting the denominator right — two traps, both of which produced a wrong answer first

- **`store/listings/*.json` is not the catalogue.** It is a local receipt. `decay.py:52-56` records
  the incident that proves it: four candidates re-vetted to KILL "kept selling live on
  mumchimp.com because store/listings/{cid}.json and Store.Api's IsListed both outlive the kill."
  Measured now: **21 of 77 receipt files have no live listing**, and two are mock fixtures (25.3).
- **`store_platform/src/Store.Api/store.db` is not the catalogue either.** It is a DEV database
  holding 13 packs including `demo-pack-001`/`demo-pack-002`. Queried in isolation it reports a
  live, selling product as absent — which nearly produced a retraction of a correct finding in this
  very section.

The catalogue is the production API: `GET https://api.mumchimp.com/catalog` → **56 live items**, all
56 carrying a dossier. Every figure below is against that.

### 25.2 The measurement — the gate is a SOLE-BASIS gate, and the residual is most of the problem

56 live items, 265 ruled checks, 1,054 cited URLs.

| tier | citations | share |
|---|---|---|
| other | 750 | 71.2% |
| government | 145 | 13.8% |
| **ugc_social (LOW)** | **108** | **10.2%** |
| established_org | 28 | 2.7% |
| media | 14 | 1.3% |
| academic | 5 | 0.5% |
| wikipedia | 2 | 0.2% |
| **stats_farm (LOW)** | **2** | **0.2%** |

UGC is *higher* in what ships (10.2%) than in the corpus at large (8.0%), so this is not a problem
concentrated in the kills.

| | live catalogue |
|---|---|
| ruled checks touching a LOW tier | **75 of 265 (28.3%)** |
| …demoted by `P1_check_aware` | **1** |
| …left standing (**residual**) | **74** |
| live items with ≥1 low-tier citation | **43 of 56 (77%)** |
| live items where the gate demotes a check | 1 (`85bf91bd2895305c`) |
| live items retaining residual low-tier evidence | **42 of 56 (75%)** |

**This is not a defect in P1 and is not an argument against having shipped it.** P1 is by
construction a *sole-basis* gate: it fires only when EVERY citation behind a ruling is
inadmissible, and §20.3 chose that deliberately because the alternative (P0) destroyed 4.3× more
evidence in the checks where UGC was the right source. The measurement here simply bounds what was
bought: on the selling catalogue the gate reaches **1 of 75** low-tier-touching rulings, because a
weak source almost always arrives alongside a plausible one.

**The founder's original observation sits in the residual, and is live and priced.**
`d8aa7528aa73eabb` — *"StorefrontShield — the ADA lawsuit-prevention kit for California small
shops"*, **£49.00**, verified live via `GET /catalog/d8aa7528aa73eabb` → `200` — has two checks
citing `gitnux.org`, and **both remain ADMISSIBLE under the shipped policy**:

| check | verdict | cited tiers | P1 verdict |
|---|---|---|---|
| `buyer_intent` | supported | `other`×3 + **`stats_farm`** | admissible — ruling stands |
| `pain_reality` | supported | `other`×4 + **`stats_farm`** | admissible — ruling stands |

Their rationales still carry the stats-farm figures — *"92% plaintiff win rate"*, *"$35,000 per
case"*, *"1.2 lawsuits per 100 firms vs 0.9 national"* — from a passage that self-describes as a
"statistics snapshot… for a stable visual baseline". A sole-basis gate cannot remove a bad NUMBER
from a rationale that also cites acceptable sources. **Source-or-die is a claim-level rule; the
shipped gate is a ruling-level one, and this is the gap between them.**

Residual low-quality domains still behind a standing ruling on the live catalogue: `facebook.com`
45, `reddit.com` 19, `linkedin.com` 12, `youtube.com` 7, `tiktok.com` 7, `instagram.com` 6,
`mumsnet.com` 6, `pinterest.com` 3, `gitnux.org` 2, `quora.com` 1.

### 25.3 Two mock fixtures are resident in `store/listings/`

`7bdca0e0cb4e0f68` and `9c4df0f3e0c5cc30` are not listings. Different schema from the other 75
(`packs{…}` + `trust_metadata`, none of `title`/`market`/`catalog`), and every field is fixture
data: `"trust_metadata": {"model": "mock", "grounding": "100% sourced"}`, evidence URLs
`https://statutory-adjudication.example.com` and `https://api-economy.example.com`, every score `4`
justified `"looks good"`, and real prices attached (£60/£180/£600). `reverify_due_at` 2026-07-13,
overdue since before anyone noticed.

**Buyer exposure is nil, measured not assumed** — both are absent from the production catalogue and
from the Store.Api pack table. The harm is to measurement: anything globbing `store/listings/*.json`
counts them as products, which is how the first pass at 25.1 got a 77-item denominator. Same defect
class as `durable-ledger-was-inert-1874-fixture-laws` and `tests-polluted-the-production-audit-log`
— fixtures resident in production state directories. A mock record asserting `"grounding": "100%
sourced"` is the most misleading possible form of it.

### 25.4 What this hands forward

| # | action | note |
|---|---|---|
| Q4b.1 **DONE §25.5** | Claim-level tracing measured: 10.3% of figures are in no retrieved passage | this is the founder's actual complaint; larger than Q4, adjacent to §14 entailment |
| Q4b.2 | Remediate `d8aa7528aa73eabb` (£49, live) — re-vet, annotate, or delist | money-rail, founder call, **not** an engine change |
| Q4b.3 | Archive the two mock fixtures out of `store/listings/`; reject schema-less writes | small, deliberate |
| Q4b.4 | Re-run Q4b after any admissibility change — it is the acceptance test for "did this reach the buyer?" | the corpus number cannot answer that |

### 25.5 Q4b.1 DONE — claim-level tracing: 10.3% of the figures in ruled rationales are in no passage we retrieved

§25.2 established the shape of the gap: the shipped gate is RULING-level, source-or-die is
CLAIM-level, so a bad number survives in any rationale that also cites an acceptable source. This
measures that gap directly. Probe: `tools/experiments/q4c_claim_level_tracing.py` — read-only, zero
LLM, zero network except the catalogue fetch under `--live-only`.

**Why the question is answerable from our own files.** `verify.py:375-376` builds the verdict prompt
as `[source_id] s.text[:VERDICT_PASSAGE_TRUNCATE]` and `VERDICT_PASSAGE_TRUNCATE = 600`
(`verify.py:477`); the instruction at `verify.py:338` is "Rule ONLY from the provided passages";
and `verify.py:469` stores `[s for s in sources if s.source_id in citations] or sources`, so a
dossier's `sources[].text` **is** the passage set. A figure absent from all of it was never
retrieved. That is a fact about our files, not an inference about the web.

**Five buckets, because "not in the cited passage" has innocent explanations and a headline that
does not subtract them is an accusation, not a finding.** Corpus snapshot 1,572 dossiers, 2,613
ruled+cited checks, 814 of them asserting at least one figure, 1,640 figures:

| bucket | corpus | current moat | LIVE catalogue | meaning |
|---|---|---|---|---|
| `traceable` | 1,323 (80.7%) | 801 (84.8%) | 141 (83.9%) | inside the 600 chars the model saw |
| `truncated` | **0** | **0** | **0** | in the stored passage but past the prompt budget |
| `self_ref` | 134 (8.2%) | 62 (6.6%) | 13 (7.7%) | our own pitch, or a `listing.pricing.rungs` price |
| `other_passage` | 14 (0.9%) | 2 (0.2%) | 0 | retrieved for the candidate, cited by a different check |
| `untraceable` | **169 (10.3%)** | **80 (8.5%)** | **14 (8.3%)** | in **no** text this run retrieved |

`truncated = 0` in all three scopes is a validity check, not a null result: if the model were
somehow seeing text beyond the 600-char budget, figures would land in that bucket. None do, which
is what confirms `s.text[:600]` is the right haystack.

**Matching is deliberately lenient, so `untraceable` is a lower bound.** A figure counts as found
if its bare digits appear anywhere in the passage with digit boundaries — `92` matches "92%",
"92 percent" and "92 of them" alike; units, currency and wording are not required. Anything this
test calls untraceable is untraceable under any stricter test. Sanity cases (8 extractor, 8
matcher) run inline and pass, including the boundary case that `35000` must not match `135000`.

**The exposure is concentrated in one check, and its residual is mostly a different defect.**

| check | figures | untraceable | rate |
|---|---|---|---|
| `payer_solvency` | 629 | 107 | **17.0%** |
| `claims_verifiable` | 100 | 16 | 16.0% |
| `route_to_market` | 12 | 2 | 16.7% |
| `incumbency` | 114 | 10 | 8.8% |
| `legality` | 28 | 2 | 7.1% |
| `value_durability` | 277 | 14 | 5.1% |
| `distribution` | 81 | 4 | 4.9% |
| `pain_reality` | 192 | 8 | 4.2% |
| `currency` / `buyer_intent` | 104 / 103 | 3 / 3 | 2.9% / 2.9% |

Reading the actual sentences shows `payer_solvency` is not mostly fabricating facts about the
world — it is **inventing a price for our own product to argue affordability**, e.g.
`8ce5270ade208070` "so a £39 audit is safely within budget", `a2c9948e0cc21cad` "so a £69 pack is
within demonstrated budget", `9d79ec9bd617b4c0` "also fits a £4.99–£9.99 fee". The rung-aware
`self_ref` bucket already absorbs £49/£149/£199 (`config.yaml listing.pricing.rungs` = 1900, 2900,
4900, 7900, 9900, 14900, 19900); £39, £69 and £4.99 are **not rungs at any tier**, so the rationale
is reasoning about a price the ladder will never mint. That is its own bug and it is not
source-or-die.

Subtracting that check gives the conservative rate for figures actually asserted **about the
world**: **corpus 62/1,011 = 6.1%; current moat 34/629 = 5.4%; live catalogue 3/93 = 3.2%.**

**On the selling catalogue: 11 of 56 live items (20%) carry at least one untraceable figure** —
`08b22037fc2afc07`, `0cc434887c47cb9a`, `1723d378cff66ebc`, `6171136b72015134` (`10127.1` in a
`claims_verifiable/supported`, cited to four US law firms), `65d1d898e62cf5b9` ("$1.68B across
134373 players", cited to `esportsearnings.com` and `calculatorcollection.org` — neither passage
contains either number), `6817348413f4658c`, `7c333417348e25ea`, `823a9920812ab3d4`,
`939b559421982379`, `ac755ca1473e57fa`, `b66e17703d0ef7c0`. Full list and per-figure context:
`tools/experiments/q4c_claim_level_tracing_receipts_live.json`.

**What this does NOT claim.** That a `traceable` figure was used correctly — only that the model
could see it. Whether the passage *entails* the sentence is the §14 entailment question and no
digit-matching probe can answer it. 80.7% traceable is therefore a ceiling on grounded figures,
not a measurement of grounded reasoning.

### 25.6 What Q4c changes about the plan

1. **The denylist instinct is now doubly wrong.** §18 killed it on relevance; §25.2 showed the
   ruling-level gate cannot reach a bad number; §25.5 shows ~1 figure in 10 is in **no** retrieved
   passage at all, so no policy over *which domains we accept* can touch it. The lever is
   claim-level, at generation time or in a post-hoc check.
2. **The cheapest real fix is a numeric-citation check, and it is deterministic.** `q4c`'s matcher
   IS the check: after a verdict returns, extract figures from the rationale and confirm each
   appears in a cited passage. It needs no model, costs microseconds, and its false-positive
   direction is already the safe one. Open question for the founder: demote the check to
   `unverifiable`, or keep the ruling and strip the offending sentence? **Not implemented — this
   section measures; §15 P-items decide.**
3. **`payer_solvency` needs its own fix and it is not a grounding fix.** The check argues
   affordability against a price it invents, sometimes off-ladder. Feeding it the actual rung from
   `config.yaml listing.pricing` would remove ~2/3 of the corpus untraceable count and make the
   argument true.
4. **`other_passage` at 0.9% is the good news** — mis-citation is rare. When a number is grounded,
   the citation usually points at the right source.

## 24. Wave 2 — §23.6 closed, and the two P0 backup gaps closed (2026-08-07)

> Numbering note: the register carries **two** `## 23.` headers (Wave 1 at the R3/R4/S5/E13 entry,
> Q4-on-the-selling-catalogue below it), landed by concurrent sessions. Left as found — renumbering a
> section other work links to costs more than the collision does. This is 24.

The brief was "fix the CLASS of defect, not the six instances". Four of the six §23.6 items are one
class — **a path that is resolved relative to the current working directory, or bound at import** —
so the fix is a module, not six edits.

### 24.1 The lost-update drain (`unlist_killed.py`) — proved before it was fixed

`QUEUE.write_text("")` empties a queue that `decay._queue_unlist` appends to concurrently, so every
entry that arrives during the `fly ssh` round-trip is destroyed unprocessed. A pack the engine has
KILLED then stays on sale, and there is no trace that it was ever queued. The failure is written down
as a test first, `tests/unit/test_jsonl_consume.py`:

```python
append_jsonl(q, {"n": 1})
entries = read_jsonl(q)              # drainer reads the queue
append_jsonl(q, {"n": 2})            # producer appends while the drainer works
q.write_text("", encoding="utf-8")   # the old drain
assert read_jsonl(q) == []           # record 2 is simply gone
```

Fix: `prospector/jsonl_atomic.consume_jsonl` — an `fcntl.flock(LOCK_EX)`-serialised read-and-rewrite
that writes back exactly the bytes appended after the read offset. `unlist_killed` retires processed
entries to `pending_unlist.done.jsonl` and prints `N entry(s) arrived while unlisting`. A run that
FAILS (a row still `IsListed=1` after the UPDATE) leaves the queue untouched and writes no done log —
asserted, because a drain that retires work it did not finish is the same data loss wearing a
different mask.

The concurrency test spawns **4 subprocess producers × 150 records** against a draining parent and
asserts conservation. It has to be subprocesses: `flock` is held per open file description, so a
single-process test proves nothing about the lock.

Receipts: `tests/unit/test_jsonl_consume.py` 13 tests, `tests/unit/test_unlist_killed_queue.py` 8 tests.

### 24.2 The two P0 backup gaps — CLOSED, with live R2 receipts

**Gap 2 (non-recursive glob).** `sync` now walks `rglob("*.json")` and keys objects by path relative
to `DOSSIER_DIR`, so `quarantine_ungrounded/<id>.json` is a distinct key from `<id>.json`. Live:

```
STORE_BACKUP PASS dossiers=1588 uploaded=48 unchanged=1540 verified=8/8
REMOTE quarantine_ungrounded=9   local=9   LOCAL FILES NOT IN BUCKET: 0
```

**Gap 1 (no db backup).** `sync` now also uploads a gzipped hot snapshot of `store/prospector.db`,
taken with `Connection.backup()` from a `file:...?mode=ro` URI (never `shutil.copy` — under WAL with
the daemon writing, a copy can capture a torn page set), `PRAGMA integrity_check` run on the
**snapshot**, dated key, retention by lexicographic sort of the ISO date. No new launchd job was
needed: the installed `com.prospector.backup.plist` already runs `scripts/backup_store.py` daily at
03:40 with `WorkingDirectory` set, so the db rides the schedule that already existed.

```
db db/prospector-2026-08-07.db.gz 493891 bytes gz, dossiers=1760
STORE_BACKUP RESTORE PASS files=1701
  restored db/prospector-2026-08-07.db.gz -> prospector.db, integrity ok, dossiers=1760
RESTORE_DRILL PASS checks=12 failures=0
  [PASS] dossier_coverage  1588 live source file(s), all present in the restore
  retained_history         1701 restored vs 1588 live — 113 object(s) the backup keeps that
                           the source no longer has
```

**The drill was asserting the wrong property, and finding that cost a false FAIL.** Its first run
against the real R2 payload failed `dossier_files restored=1701 source=1588` while `index_vs_tree`
PASSED — every live row had a restored file. A cumulative bucket legitimately holds more than the
live tree. **Backup coverage is MEMBERSHIP, not count**: count-equality can pass while N files are
missing and N stale ones are present. `verify_counts` now checks that every live source file is in
the restore and reports the surplus as a note; two tests pin the replacement, including one where an
unindexed live source file is dropped from the payload — `dossier_coverage` fails while
`index_vs_tree` still passes, which is exactly the hole the old check had.

Receipts: `tests/unit/test_backup_store_coverage.py` 18 tests, `tests/unit/test_restore_drill.py`
17 tests.

### 24.3 The class itself — `prospector/paths.py`

A cwd-relative `Path("store/...")` fails two ways, and the second is the expensive one: run the
daemon from anywhere but the repo root and it reads and writes a *phantom* `store/`; bind it at
import and no test fence can redirect it afterwards. That second mode is the documented cause of
fixture rows in the production audit log and 1,874 fixture `LAW:` lines in the durable ledger.

`paths.py` resolves **per call** from an `ANCHOR` derived from `__file__`, with
`PROSPECTOR_REPO_ROOT` / `PROSPECTOR_STORE_ROOT` overrides (store wins, so a fixture can redirect
runtime state without faking a whole repo). `tests/unit/test_paths.py` pins the property a constant
cannot have: it imports a consumer FIRST, then moves the root, and asserts the consumer follows —
plus subprocess inheritance, because most of this code (daemon, backfill driver, cockpit runner)
runs as its own process.

Converted: **19 call-time cwd-relative literals**, all in `prospector/control_center/` —
`readers.py` (13), `pages/_resume.py` (3), `runner.py` (2) — plus `decay.py` and `unlist_killed.py`
from the §23.6 list. Grep for the literal in that package now returns nothing.

**Left alone, deliberately:** 9 module-level constants that are already `__file__`-anchored
(`audit.py:134 _AUDIT_DIR`, `health.py:31/37`, `pipeline/middleware.py:26`, `prompts.py:17`,
`retrieval.py:36`, `run.py:167`, 2 in `tools/experiments/`). They are import-bound but not
cwd-relative, i.e. the lesser half of the defect, and `audit.py` is already fenced by
`tests/conftest.py:37-38` patching both the env var and the module attribute. Churning the audit hot
path to remove a hazard a fence already covers buys nothing.

`runner.py:104 _production_jobs_file()` deliberately does NOT route through the `_jobs_file()`
accessor: it is the guard that answers "is this the real production jobs file?", so it must resolve
the anchored path even when a test has redirected the accessors. Anchoring made that guard stronger,
not weaker — it used to be cwd-relative, which is to say it could be fooled by a `cd`.

### 24.4 `PYTHONPATH` is no longer required

`pytest.ini` gained `pythonpath = .`. Proof is running it with the variable actively removed, from a
foreign cwd:

```
$ cd /tmp && env -u PYTHONPATH <repo>/.venv/bin/python -m pytest <repo>/tests/unit/test_paths.py -q
7 passed
```

### 24.5 A lint receipt now exists

`ruff 0.16.2` is in `.venv` and in `requirements.txt`; the rule set is pinned in `ruff.toml` because
installing ruff alone would not have produced a usable receipt — unconfigured it reports **1085**
findings on ruff 0.16 and the set drifts with the version, so two checkouts would disagree about
whether the tree is clean. Pinned to `E4/E7/E9/F/I`, the measured baseline is **393**, itemised in
`ruff.toml` along with both moves it has already made. Not yet wired into the commit gate; the number
is the ratchet.

The path conversion added **zero** findings — each touched file was checked against its own HEAD
version via `git show HEAD:<f> | ruff check --stdin-filename <f> -`.

### 24.6 Receipts, whole-tree

```
full suite          1875 passed, 3 skipped in 1390.08s   exit 0
the five new/changed suites   59 passed in 24.65s        exit 0
POPDD python lane   1877 passed                          exit 0
ruff  prospector/ tools/ scripts/ tests/   393 findings (baseline, unchanged by this work)
```

**One test had to be fixed to get there, and it is not a defect in the code under test.**
`tests/control_center/test_auth.py::test_unconfigured_portal_fails_closed` failed four runs in a row
with `RuntimeError: AppTest script run timed out after 3(s)` and then BLOCKED the POPDD gate
(`1876 passed, 1 failed`). It is not this branch: `auth.py` imports only `hmac`, `os` and
`streamlit`, it passed inside the green full-suite run above, and *which* of the two AppTest tests
fails changes with run order — whichever goes first. Streamlit's `AppTest` deadline is 3
**wall-clock** seconds (`local_script_runner.require_widgets_deltas`), and the box was at
`load averages: 210.54` with three concurrent-session pytest processes and a graphify refresh on it.

A wall-clock deadline that short is a load meter, not an assertion — none of the five assertions in
that file is about speed. Fixed at the construction site,
`AppTest.from_function(_gated_app, default_timeout=60)`, which is inherited by the chained
`at.button[0].click().run()` calls too. `5 passed in 1.30s` — a genuine hang still fails.

### 24.7 What this hands forward

| # | action | note |
|---|---|---|
| W2.1 | ~~Decide whether the `AppTest` deadline should be raised~~ **DONE, §24.6** — `default_timeout=60`. `test_auth.py` is the only `AppTest` user in `tests/`, so there is nothing else to raise; re-apply the same at the construction site if another one is written | a 3s wall-clock deadline is a load meter, not an assertion |
| W2.2 | Ratchet the 393 ruff findings down; the 10 `F821` first | an undefined name is a NameError waiting for its branch |
| W2.3 | Wire `ruff check` into the POPDD gate once the baseline is 0 | a gate whose first act is a 700-file autofix gets turned off |
| W2.4 | Renumber the duplicate `## 23.` sections in this register | cosmetic, but it breaks cross-references |
