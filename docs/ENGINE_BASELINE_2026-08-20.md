# Engine baseline, 2026-08-20

The first reading of every axis in `docs/ENGINE_100X_PROGRAM.md` from one command.

```bash
.venv/bin/python tools/engine_baseline.py --store <store>          # print
.venv/bin/python tools/engine_baseline.py --store <store> --write  # save a dated copy
```

Before today, five of the eight axes had no baseline at all. An axis with no unit cannot be
improved by a thousand times, because nobody can say what a thousand times of it is. The harness
therefore refuses to print a blank: every axis returns a number with its provenance, or the
literal string `UNOBTAINABLE` with the reason it cannot be read. Nothing here calls a model, so
it runs while the engine is blind, which is when it is most needed.

## What was read

Corpus: `/Users/chidionyema/Documents/code/wt-cheapclaude/store`, fingerprint `d66f09d0544fd796`,
frozen, newest dossier 2026-08-18T00:27:35Z. **2,806 dossiers of 2,929 files, 14,006 checks,
123 non-dossier json skipped.**

This is a SNAPSHOT, not the live store. The canonical local store
(`/Users/chidionyema/Documents/code/prospector/store`) holds zero dossiers; the live corpus is on
the Fly volume at `/data`. Read every number below as "the engine as it behaved up to
2026-08-18", not "the engine right now".

## The axes

| Axis | Reading | Note |
|---|---|---|
| A1 availability | `UNOBTAINABLE` | `provider_health.json` absent from this snapshot. On the canonical store it exists; on the Fly box it is the one that matters and this session cannot reach it. |
| A2 throughput | **0.0/hour trailing 24h**, 6.083/hour trailing 7d, 1.844/hour lifetime | Nothing written in the last 24 hours of the snapshot. Newest dossier 2026-08-18, oldest 2026-06-15. |
| A3 latency | `UNOBTAINABLE` | **No per-stage timer is recorded anywhere in a dossier.** A dossier carries `created_at` and nothing else time-shaped, so start-to-finish cannot be reconstructed after the fact. This is a defect, not a gap in the harness. |
| A4 discrimination | **100.0%** on 9 cases, from `minimax_20260815T111104521041.json`, 77 stored runs | Saturated. See below. |
| A5 yield | **38.5 PASS per 1000** (108 of 2,806; kill 2,698) | This is passes per thousand, not survival of founder review. Nothing records a review outcome, so that half stays `UNOBTAINABLE`. |
| A6 cost | **$0.1893 median per candidate vetted** (mean $0.2452, min $0.1078, max $0.5568, n=9 candidates over 38 priced calls) | Corrected 2026-08-20. The earlier `UNOBTAINABLE` was measured against the wrong store. See below. |
| A7 grounding fidelity | **2.92%** [2.43, 3.51], null control **0.0%** [0.0, 0.1] | New metric, defined below, and it passes its own control. |
| A8 abstention | **26.71% attempted** — unverifiable 10,265, supported 3,079, refuted 662 of 14,006 | 73.3% abstention, and 95.3% of it had relevant passages in hand (E-105). See below. |

Cost anatomy from the same pass: 2,806 vets, **4.991 model calls per vet on average, median 6**,
1,420 of them full six-check vets (50.6%). Median evidence payload 1,500 characters, mean 2,878.

## The four findings that matter

### 1. A candidate costs $0.1893 to vet — and the first answer here was wrong

**CORRECTED 2026-08-20.** This section previously read "not one row in the ledger carries a cost
field", and A6 reported `UNOBTAINABLE`. That was a measurement against the **wrong store**. The
snapshot store the harness was pointed at has no priced rows; the canonical ledger,
`/Users/chidionyema/Documents/code/prospector/store/prospector.jsonl`, has 528 rows of which 39
carry `cost_usd`. The meter existed the whole time. This is the
`the-canonical-store-is-the-empty-one` trap firing on my own instrument, and a single angle gave
the wrong answer — exactly what LAW 15 exists for.

The number, from the Claude CLI's own billed figure:

| | |
|---|---|
| **median USD per candidate vetted** | **0.1893** |
| mean | 0.2452 |
| min / max | 0.1078 / 0.5568 |
| candidates priced | 9 |
| priced calls | 38 |
| median calls per vet | 3 |
| attributed spend | $2.2065 |
| unattributed (costed rows naming no candidate) | $0.0391 over 1 call |

**Median, not mean, and that choice is the finding.** The spread is 5.2x from cheapest to dearest
vet, because retries land on one candidate. The mean tracks that tail; the median answers "what
does a typical candidate cost us", which is the number a budget is built from.

**The axis no longer divides one population by another.** It used to compute total ledger spend
over the corpus check count. The ledger and the dossier corpus are different populations over
different time windows, so that quotient was arithmetic wearing a measurement's clothes — and
with an empty corpus it printed `UNOBTAINABLE` against a fully populated cost meter. It now
self-joins on the `candidate_id` carried inside the cost row itself, and reports rows that carry
a cost but name no candidate separately rather than dropping them.

**Provenance, and it bounds the number.** All 39 priced rows carry `message: "Claude CLI usage"`
and span 2026-08-20 19:46:05 to 21:10:32 — 84 minutes of **local runs on this laptop**, not
production. `com.prospector.scheduler` is off by design here; the engine has run on Fly
(`prospector-engine`) since the 2026-08-18 cutover, and this session cannot reach that box's store.
So this is a real measurement of what a vet costs, taken on the wrong host. Treat it as an order of
magnitude for production, not as production's bill.

**Two things it therefore does NOT measure.** First, `cost_usd` is the Claude CLI's own
self-reported figure, which is notional retail on a subscription already paid for — it is what the
work WOULD cost at API prices, not cash leaving the account. Second, and worse for the cost
programme: **MiniMax, the configured head and a trusted-final brain, emits no cost row at all.**
74 ledger rows mention minimax; 0 carry a cost field. The meter prices the fallback and is blind to
the primary.

**Why Claude CLI served every call in this window.** MiniMax was quota-exhausted throughout:
`provider_health.json` records 4 strikes and `"MiniMax quota exhausted: HTTP Error 429 — Token Plan
usage limit reached: Upgrade your Token Plan or purchase Credits"`, breaker open, re-probe backing
off 120s → 240s → 480s → 600s. Buying credits is money leaving the account, so it is the founder's
call, not an agent's. Verdicts still finalised correctly because `claude_cli` is also inside
`moat_primary`, so nothing was stamped provisional — the engine was degraded, not down.

**A perf cost inside that failover (LAW 14), measured, unfixed.** Each exhaustion burned the full
retry ladder before failing over: 5s + 10s + 20s + 40s = **75 seconds of sleep per occurrence**, 5
occurrences = 6m15s of pure wall-clock in an 84-minute window. The classifier does eventually mark
it permanent, so the strikes work; the waste is the four retries against a provider whose error
text already says the token plan is exhausted.

**Still unmeasured:** cost per PASS. 9 priced candidates is too few to contain a representative
number of passes, and A5 says only 38.5 in 1,000 pass. The $3.60 per 1,000 verdicts in the
programme doc remains an estimate and should be replaced once the ledger has attributed a few
hundred vets.

**One cost finding, not yet fixed, with the number attached (LAW 14).** Across those 39 priced
calls, prompt-cache WRITE tokens were 841,319 against cache READ 524,698 — a ratio of **1.60**,
with write exceeding read on **39 of 39 calls**. Cache write bills at a premium over ordinary
input; a stable prefix would show read dominating. The prefix is being rebuilt on nearly every
call. Before any caching change ships, the guard is: assert `cache_read + cache_creation > 0` on
the SECOND call. Below the provider's minimum cacheable prefix (4,096 tokens for Claude Haiku 4.5
and Gemini 3.x Flash; our preamble measures 2,813) the API returns 200, reports
`cache_creation_input_tokens: 0`, and bills full price forever.

### 2. A4 is saturated, and its unsaturated companion was sitting in the same file

Discrimination is 1.00 on nine items. It can register neither an improvement nor a regression,
which is why E-040 to E-045 are unrunnable rather than merely unrun.

**Gate accuracy is in the same file, is excluded from the score, and is not saturated.** It counts
how often the gate that fired is the gate the golden case labelled. Two readings:

- stored run `minimax_20260815T111104521041.json`: **4/9, 44.4%**
- live run through the current brain chain, 2026-08-20: **7/9, 78%** — the two misses were
  `value_durability` fired where `distribution` was expected, and `distribution` fired where
  `legality` was expected.

That is a live, unsaturated quality number that needs no new labels, no money and nobody's
permission. It is the interim quality axis to use while the golden set is being resolved.

**Defect found while reading this.** `prospector/golden.py:396` writes the audit record to
`<store>/golden_runs/`. The canonical store has no `golden_runs` directory, so today's live 9/9
run left no receipt anywhere — the only copy of that measurement is a terminal transcript. Every
stored run in the estate is from 2026-08-15 or earlier.

### 3. A7: a grounding instrument that is free, deterministic, and passes its own control

**Definition.** The percentage of ruled checks (supported or refuted) whose rationale shares a
literal run of 12 consecutive words with a passage it cites. Twelve words is long enough that
agreement by chance is negligible and short enough that a paraphrase of one clause still counts.
This is the rule `price_comparables` already enforces on its anchors, applied as a measurement
rather than as a gate.

**Reading: 2.92%**, 109 of 3,732 ruled checks, Wilson 95% [2.43, 3.51].

**The control.** An absolute rate means nothing until you know what the metric reads on evidence
that cannot be the source. E15 learned this expensively: its tau was calibrated on a null control,
and two runs 40 minutes apart moved it from 0.0589 to 0.0691. So the harness re-scores every
rationale against a DIFFERENT check's passages, at a fixed offset of half the population so a
re-run over the same corpus gives the same answer.

**Null control: 0.0%**, Wilson [0.0, 0.1]. The two intervals do not overlap. The metric is
reading grounding, not boilerplate every passage shares.

**What it is not.** It is a lower bound on fidelity and an upper bound on nothing. A perfectly
faithful rationale that paraphrases every clause scores zero. It does not replace E15's entailment
measurement and it does not replace human labels. What it does is move when the engine changes,
cost nothing, and never need a brain — which is what an instrument has to do.

### 4. 73.3% abstention — a hypothesis with a named test, NOT a finding

Full evidence and sources in `docs/RESEARCH_EVIDENCE_RECALL.md`. The short form: the comparable
published human rate is **6.2% to 9.2%** (AVeriTeC, 4,568 real claims, live-web evidence, human
annotators). We are 8 to 12 times it.

An independent second angle says the same thing. In the AVeriTeC shared task every system ran
against an identical fixed corpus; the baseline scored 0.11 and the winner 0.63, so the entire
gap is query quality rather than corpus availability.

**Corrected the same day by our own corpus, and the correction is why this is no longer called a
finding.** E-105 (`tools/experiments/e105_unverifiable_prefilter.py`, full write-up in
`docs/RESEARCH_CHEAP_INFERENCE.md` section 5) passed over all 14,006 checks and found that
**9,784 of the 10,265 unverifiable checks — 95.3% — already had passages in hand that shared an
entity or a number with the query.** Only 481 (4.69%, CI [4.29, 5.11]) had nothing usable
retrieved at all.

So the two angles disagree. The published human rate says we abstain 8–12x too often and the
shared-task result blames query quality; our own corpus says the text mostly came back and the
brain declined to rule on it anyway. Both cannot be the whole story, and under LAW 15 the
disagreement outranks either reading.

**Nobody should claim the abstention rate is a defect or that it is correct until the third
instrument exists.** That instrument is the human-labelled set, action plan item 1.2, because it
is the only one that can say whether those 9,784 checks were correctly unverifiable or wrongly
abstained. This section previously asserted the defect version; that was one angle stated as a
conclusion.

Two cheap tests remain worth running, in this order:
1. Re-decompose a failed claim into a different question set and search again. Stable-empty across
   two independent question sets is evidence of true absence; a flip is evidence we searched badly.
2. Sample from the 9,784 rather than from all failures. That population is where the answer is,
   and it is a different sample from the one the retrieval research assumed.

## What the harness refuses to do

- It never prints zero where it means "could not read". A5 returns `UNOBTAINABLE` rather than 0.0%
  when no dossier carries a decision field, because 0/0 dressed up as 0% is the failure this whole
  file exists to prevent.
- It skips files in `store/dossiers` that are not dossiers — pack lint reports, mostly, 123 of
  them here. Counting those as dossiers drags every rate toward zero while still printing as a
  measurement.
- `--store` redirects the corpus reader as well as the report header. Without that it would read
  one store's dossiers and print another store's ledger, and the two numbers would look like they
  came from the same place.
- It records the corpus fingerprint on every run, so two readings are comparable rather than
  merely similar.
