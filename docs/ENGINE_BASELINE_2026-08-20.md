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
| A6 cost | `UNOBTAINABLE` | **No ledger row carries a cost field.** See below. |
| A7 grounding fidelity | **2.92%** [2.43, 3.51], null control **0.0%** [0.0, 0.1] | New metric, defined below, and it passes its own control. |
| A8 abstention | **26.71% attempted** — unverifiable 10,265, supported 3,079, refuted 662 of 14,006 | 73.3% abstention, and 95.3% of it had relevant passages in hand (E-105). See below. |

Cost anatomy from the same pass: 2,806 vets, **4.991 model calls per vet on average, median 6**,
1,420 of them full six-check vets (50.6%). Median evidence payload 1,500 characters, mean 2,878.

## The four findings that matter

### 1. We cannot measure what the engine costs to run

A6 is `UNOBTAINABLE` because **not one row in the ledger carries a cost field.** The $3.60 per
1,000 verdicts in the programme doc is an estimate, and it has always been an estimate.

The founder's goal is "as cheap as possible to run while being 1000x better". Cost is now a
target, and a target with no meter cannot be hit or even aimed at. Writing a real per-call cost
into the ledger is the highest-priority instrument in the plan, ahead of every optimisation,
because every cost win claimed before it exists is a claim nobody can check.

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
