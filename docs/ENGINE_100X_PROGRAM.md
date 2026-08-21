# The 100x Engine Programme

**Status: OPEN. Started 2026-08-20.** Branch `perf/engine-100x`, worktree
`/Users/chidionyema/Documents/code/wt-engine100x`, based on `origin/main` at `8c0c821e`.

**The headline number is 1000x, not 100x (founder, 2026-08-20: "1000x is the headline of the
project", "we want 1000 inprovebtbts all ways").** The filename still says 100X because renaming a
tracked doc breaks every reference to it; the target it carries is 1000x on every axis in section 1.
Measured the same day: only two files in this repo mention 1000x at all, both incidentally, so the
number lived in the founder's head and nowhere else until this paragraph.

This file is the programme's single record. Every experiment gets a row in section 4 whether it
worked or not. A failed experiment that is not written down will be run again by somebody else.

---

## 0. The founder's wishes, verbatim

Captured 2026-08-20 across one exchange. Reproduced exactly as typed, because a wish paraphrased
is a wish reinterpreted.

1. *"ok yyou need to leave notes on wwhere you are on hernes agent work, ship it for now, new
   branch and work tree and eperinent freely, ehuase all options, benchnark stritly, goal is to
   nake the engine, indepenent of cost and inrpove by a great deal of orders of nagnitude in every
   way conceivable, netric for everything and strong prrof, any resource you need is available"*
2. *"docunent rigorously and carefully"*
3. *"high bar"*
4. *"note it all down"*
5. *"all eperinets and outcones"*
6. *"we wan 100 inprovenent all round"*
7. *"even if we dont get 100 we ain for it"*
8. *"dont be afarid to reserach deep and try things and be creative"*
9. *"any chance to inprove, optiise, scale, etc"* / *"in every way possible"*
10. *"note down all ny wihes"*
11. *"i want this to be state of the art engine"*

### Later the same day, superseding two of the rules below

12. *"1000x is the headline of the project"* / *"we want 1000 inprovebtbts all ways"* — the target
    is a thousandfold, on every axis, not a hundredfold.
13. *"if it for one of exprinents fine ... if thats ging to be an operational cost then need nore
    cretaive olutions"* — a ONE-OFF experiment cost is acceptable; an OPERATIONAL cost that bills
    forever demands a different answer. **This supersedes wish 1's "independent of cost".**
14. *"cost esitbates first dicunented"* — the cost estimate is written down BEFORE the experiment
    runs, not after.
15. *"evidence has to converge fron nultiple angles"* / *"with evidece and proof"* / *"no
    guesswork"* — one measurement is a reading; two independent readings that agree are a proof.
16. *"disucs idead, edge cases with peers but bias towards action"* / *"doing over narrating is
    favoured"* — broadcast a plan to peers for the edge case you cannot see, then act.

17. *"what is the idea generation lacking to psh it to the next level of enganenent, in talking
    dragon den, sharktank level of ideas"* — the headline question of 2026-08-21.
18. *"needs special attention"* / *"super crtical"*
19. *"we need engagent as well as viablity"* — engagement is a SECOND axis beside viability, not a
    replacement for it.
20. *"for sales"* — engagement is wanted because it sells, so the metric has to be buyer-facing.
21. *"everything fron healie/title crafing to content crafing"* / *"and pack crafting"* — the scope
    runs the whole way from the idea to the document the buyer reads.
22. *"needs 1000x inprovenet"*
23. *"researcch like a possesed agent"*
24. *"add to notes"* / *"deep link"*
25. *"we need to docunent where these dossiers live, and nake it claer in pos panel, part of
    extrenen visibility, follow the pattern"*

### What that translates to, operationally

| Wish | Operational rule for this programme |
|---|---|
| independent of cost | **SUPERSEDED 2026-08-20 by wishes 13 and 14.** A ONE-OFF experiment cost is acceptable and no experiment is rejected for being expensive. An OPERATIONAL cost — one that bills forever and grows with volume — is a target like any other, and every experiment posts a cost estimate before it runs. |
| 1000x, all round | Every axis in section 1 carries a **1000x** target (was 100x until wish 12). Aim for it even where it is not reachable; record the number actually reached. |
| evidence converges | No axis moves on one measurement. Two independent angles that can fail differently, and the reply names both. A disagreement between them outranks either. |
| benchmark strictly | Section 2 is the admissibility bar. A number that fails it does not go in the ledger. |
| metric for everything | No axis without a unit, a baseline, and a command that reproduces it. |
| strong proof | Every ledger row carries a receipt: a command, a commit SHA, and the raw output location. |
| exhaust all options | Section 3 is the backlog. It is closed only when every row is DONE or REJECTED-with-a-reason. |
| all experiments and outcomes | Negative results get rows. See section 4's rule. |
| state of the art | Section 5 tracks what the literature and the open-source field do that we do not. |
| any resource is available | Hosted models, paid APIs, local models, extra machines are all in scope. |
| engagement as well as viability | Section 9. Engagement is a new axis with its own unit and baseline. It may RANK survivors and STEER generation. It may never un-KILL a candidate that failed a grounding gate — "two loops never merge" is unchanged. |
| title, content and pack crafting | The buyer-facing half is measured in section 9.3 and has its own baselines. A copy change ships against a number, never against taste. |
| extreme visibility of the corpus | `prospector/ops/data.py::_corpus` reports the store path, whether it is the production path, catalogue rows and on-disk dossier files, and reports `unknown` with the error text rather than rendering a failed read as zero. |

---

## 1. The axes, their units, and their baselines

An axis with no unit cannot be improved by 100x, because nobody can say what 100x of it is.

| ID | Axis | Unit | Baseline | Target | Baseline status |
|---|---|---|---|---|---|
| A1 | Availability | % of wall-clock hours the engine can mint a TRUSTED verdict | 0% (2026-08-20: MiniMax 429, claude_cli not logged in) | 99.9% | measured, degenerate |
| A2 | Throughput | candidates fully vetted per hour | TBD | 100x | NOT MEASURED |
| A3a | Latency p50 | seconds, candidate in to verdict out | TBD | /100 | NOT MEASURED |
| A3b | Latency p95 | seconds, same | TBD | /100 | NOT MEASURED |
| A4 | Discrimination | golden-set accuracy | 1.00 on 9 items | see below | measured, NO RESOLUTION |
| A5 | Yield | PASSes per 1000 candidates that survive founder review | TBD | 100x | NOT MEASURED |
| A6 | Cost | USD per 1000 verdicts | ~$3.60 (MiniMax M3, 10k in / 500 out assumed) | **operational cost is a target** (wish 14) | estimated, not measured |
| A7 | Grounding fidelity | % of ruled checks whose rationale shares a literal 12-word run with a passage it cites | **2.92%**, 109 of 3,732 ruled checks, Wilson 95% [2.43, 3.51] | 100% | **MEASURED 2026-08-20** — [instrument and null control](ENGINE_BASELINE_2026-08-20.md#3-a7-a-grounding-instrument-that-is-free-deterministic-and-passes-its-own-control) |
| A8 | Abstention calibration | accuracy on attempted, vs % attempted | TBD | see E-045 | NOT MEASURED |

### A4 is the blocker, and it is the first finding of this programme

Discrimination is **1.00 on a 9-item golden set**. That is not a good score. It is an unusable
instrument. A benchmark that is already saturated cannot register any improvement, and cannot
register a regression either. Every quality claim this programme makes would be unfalsifiable
against it.

So experiment **E-001 blocks every quality experiment**: build a golden set with resolution.

### A6: a one-off cost is free, an operational cost is a target

**This section said the opposite until 2026-08-21, and four places in this document still ran on
the old rule.** The correction was made at line 69 (`independent of cost` -> SUPERSEDED) and nowhere
else, which is this estate's most-repeated class: a fix applied to one of several identical sites.
The three other sites are corrected in the same commit as this one.

The founder's opening words were *"indepenent of cost"*. His later ruling splits that in two:

- A **ONE-OFF** cost -- an experiment, a migration, a rented box that gets destroyed -- is
  acceptable, and no experiment is rejected for being expensive. What is required is that the
  estimate is written down BEFORE the run, in this document.
- An **OPERATIONAL** cost -- one that bills forever and grows with volume -- is a target like any
  other, and an answer that swaps an API bill for a rented-CPU bill is not a saving.

Both halves are load-bearing. E-101 is the worked example: $12 of one-off spend was correct and
bought the answer, and Stage B was killed precisely because 0.04 pairs/s on rented CPU would have
been an operational cost forever.

Cost is still recorded so that a 100x latency win bought with a 1000x cost increase is visible as
what it is. It is no longer true that cost can never reject an experiment.

---

## 2. Benchmark admissibility — the strict bar

A measurement that fails any of these is not admitted to the ledger. These are not style
preferences; each one is a specific way this estate has already been fooled.

1. **A number with no reproducing command is not a number.** The command goes in the ledger row,
   verbatim, runnable.
2. **Measure the thing, not a wrapper around it.** A sleep profiler charges background daemon
   threads to whatever span happens to be open: it reported two tests at 35s and 30s that
   `pytest --durations` put at 0.28s and 0.22s. Source: peer session `prospector-20`, 2026-08-20.
3. **Report p50 and p95. Never a bare mean.** A mean over a bimodal latency distribution describes
   no run that ever happened.
4. **n >= 3, and report the spread.** One sample is an anecdote.
5. **Name the baseline commit SHA in every comparison.** A/B against a moving tree measures the
   tree.
6. **State the refuting outcome BEFORE running.** Write down what result would kill the hypothesis.
   An experiment with no failure condition is a demo.
7. **Fixtures for anything network-bound**, or the number measures the internet on that day.
   `retrieval.py` already has the fixture path.
8. **Never compare across different store states.** `store/` is live input. Pin it or clone it.
9. **A green suite proves nothing until you prove it can go red.** Mutate the code under test and
   confirm the benchmark or test actually fails. Anchor the mutation on a UNIQUE string: an earlier
   mutation in this estate hit the first of three identical lines and produced a false green.
10. **Check the collected count.** `pytest` exits 0 when it collects nothing. Assert the item count.

---

## 3. The experiment backlog

"Exhaust all options" means this list is worked to exhaustion, not sampled. Rows move to section 4
when run. Ordering within a group is by expected effect, not by ease.

### Group 0 — instrumentation (blocks everything)

| ID | Hypothesis |
|---|---|
| E-001 | A golden set large and hard enough to have resolution can be built from the existing `store/dossiers` corpus (2931 entries) plus deliberate near-miss negatives. Without it, no quality claim in this programme is falsifiable. |
| E-002 | A single harness can measure A2/A3/A7 in one run against a pinned store snapshot, so the six-claims-one-script rule applies to every later experiment. |
| E-003 | Per-stage timing already exists in `telemetry.py` but is not aggregated per-candidate. Aggregating it gives the latency breakdown that tells us which stage to attack. |

### Group 1 — availability (A1: currently 0%)

| ID | Hypothesis |
|---|---|
| E-010 | A local entailment classifier (Bespoke-MiniCheck-7B or HHEM-2.1-Open via the Ollama daemon) can rule `supported`/`refuted`/`unverifiable` well enough to run as a PROVISIONAL tier, taking A1 from 0% to ~100% for the drain. Fences already exist: `is_provisional_provider` (`operator.py:1451`) bars publication on PASS (`run.py:864`). |
| E-011 | Roster breadth is the cheapest availability win. Cohere Command A+ (14.2% AA-Omniscience hallucination rate, better than MiniMax M3's 18.4%) is the only untested model worth a golden-set run. Groq / Together / Cerebras host open-weight models on separate quotas. |
| E-012 | Multiple keys on one provider, rotated on 429, removes single-quota outages without adding a model. |
| E-013 | Hedged requests (fire at two providers, take the first to answer, cancel the other) convert a slow provider into a fast one and a dead provider into a non-event. Cost roughly doubles, which this programme does not care about. |

### Group 2 — latency (A3)

| ID | Hypothesis |
|---|---|
| E-020 | The six checks run SEQUENTIALLY under kill-fast. Kill-fast is a COST optimisation, and its cost is OPERATIONAL, so under wish 14 it is a target rather than a free trade (this hypothesis was written when cost was declared not a constraint; see A6 above). Running all six concurrently and cancelling on the first hard fail should cut p50 by close to 6x on candidates that survive, at the price of wasted calls on candidates that die early. |
| E-021 | Query generation, retrieval and the verdict call are three serial round trips per check. Pipelining check N+1's retrieval against check N's verdict hides most of the retrieval latency. |
| E-022 | Retrieval fetches pages serially. Concurrent fetch with a bounded pool. |
| E-023 | The six check prompts share a large system preamble. Provider prompt caching should cut both latency and tokens on checks 2-6. |
| E-024 | Batch endpoints, where a provider has them, for the drain (which is throughput-bound, not latency-bound). |
| E-025 | Speculative execution: start verify before prescreen concludes, discard if prescreen kills. |

### Group 3 — throughput (A2)

| ID | Hypothesis |
|---|---|
| E-030 | Candidate-level parallelism. The engine processes one candidate at a time; nothing in the moat is shared mutable state except the store append. |
| E-031 | The drain is trusted-only AND serial. The trusted-only part is a deliberate correctness rule and stays. The serial part is not. |
| E-032 | Async I/O end to end in `retrieval.py` rather than thread-per-fetch. |

### Group 4 — quality (A4, A7, A8) — A7 is measured; A4 and A8 are still blocked on E-001

A7 came off this list on 2026-08-20 and the reading is the finding: **2.92%**, against a null
control of **0.0%** [0.0, 0.1]. The control is what makes the number usable — the instrument
reads zero on evidence that cannot be the source, so 2.92% is real signal and not a floor.
It says the verdicts are almost never quoting the passages they cite. E-044 (generalise
`price_comparables`' literal-anchor rule to all six checks) is the cheapest thing that moves
it, and it needs no model change at all.

| ID | Hypothesis |
|---|---|
| E-040 | Ensemble verdicts: N independent models rule each check, disagreement forces `unverifiable`. This is a direct mechanisation of the engine's own abstention rule, and abstention is what the moat is FOR. |
| E-041 | An adversarial second pass on every PASS (not just a sample) catches the false positives that cost the most. |
| E-042 | Retrieval is the bottleneck on quality, not the model. Memory `grounding-bottleneck-is-relevance-not-availability` already says so. RM3 pseudo-relevance feedback over the first hit set, plus more sources, plus passage dedup. |
| E-043 | A local cross-encoder reranker over retrieved passages before the verdict call raises A7 more cheaply than a better verdict model. |
| E-044 | Generalise `price_comparables`' rule — every anchor must appear literally in the cited passage — to all six checks. This makes A7 enforceable rather than aspirational. |
| E-045 | Calibration: measure accuracy-on-attempted against percent-attempted, and tune the confidence floor to sit at the knee. AA-Omniscience's finding that MiniMax M3 attempts only 30.9% is a feature here, and it should be a tuned number, not an accident of the model. |

### Group 5 — structural

| ID | Hypothesis |
|---|---|
| E-050 | Cascade: a local classifier screens every check, and a hosted model is called only on the ambiguous middle band. Buys availability, latency and cost at once, at the risk of the local model's blind spots setting the agenda. |
| E-051 | Split the roles: one model generates disconfirming queries, a different one rules. They are different skills and the estate currently buys both from the same tier. |
| E-052 | Self-consistency: sample the verdict k times at temperature and take the majority. Cheap to try, well-evidenced in the literature, and it interacts with E-040. |

---

## 4. The experiment ledger

**Rule: every experiment that is RUN gets a row, including the ones that fail.** A negative result
costs the same to produce as a positive one and saves the next session from repeating it. A row
with no receipt is not a result.

Columns: ID | date | hypothesis | refuting outcome stated up front | method | result | verdict |
receipt.

| ID | Date | Result | Verdict | Receipt |
|---|---|---|---|---|
| E-100 | 2026-08-20 | The HHEM sidecar lived under `/tmp`, which macOS emptied. Every published HHEM number had become unreproducible: the experiment could no longer be re-run at all. Rebuilt under `~/.local/share`. The `numpy<2` prohibition in the docstring was found to be false — that pin is REQUIRED by torch 2.2.2, not a hazard. | **RESOLVED** | `tests/unit/test_experiment_sidecar_path.py`, 7 tests, mutation-proved 2 RED + 1 RED. Section "E-100" below. |
| E-101 | 2026-08-20 | Can a local open verifier rule the moat's verdicts? 8 arms scored, 3,472 pairs each, 3 lexical baselines included so a neural arm that loses to string overlap is visible. Two angles, because agreement with our own rulings is contaminated by E15's 48.9% rationale infidelity: (a) AUC against the moat's own decisions, (b) a control of cited premises against constructed unrelated ones, labels by construction. | **DONE — the answer is NO.** Angle (a): 0.476–0.562, a coin toss. Angle (b): best arm **0.706 AUC**, worst **0.408**, below random. Throughput 0.04 pairs/s on rented CPU, which would have been an operational cost forever. Stage B killed before spending a further ~$50 and 55 hours. Total spend $12; the 16-core box and its 60GB volume were destroyed the same turn. | `tools/experiments/_verifiers.py`, `_verifier_sidecar.py`, `_prove_causal_wiring.py` (17 checks, mutation-proved 4 RED). Section "E-101" below. Padding control: `e101_stageB_fly.py:183` left-padding verified, right padding moves a score 0.249 while left differs from batch=1 by 0.0023. |
| E-103 | 2026-08-20 | What does one verdict actually cost us, and is merging the six per-candidate check calls into one worth building? Two independent angles: call count from the dossier corpus, token anatomy from the prompt files on disk. | **DONE.** Corpus n=1,696 completed vets, 2,929 dossiers, 14,006 checks. **4.679 paid model calls per vet** (median 6); 60.1% of vets run all six checks; kill-fast rarely fires because `refuted` is only 4.7% of checks. Fixed preamble is ~11,250 chars on EVERY call (template 4,895 + style 1,247 + exemplars 885 + candidate median 4,220) against 1,500 chars of actual evidence — **7.5x more boilerplate than evidence**. Merged: ~59,700 → ~21,450 input chars per vet = **2.8x on tokens, 4.679x on calls**. My earlier "up to 6x" was wrong and was corrected to the founder unprompted. Founder ruling: *"ok let doi it regardless, add to list"*. | Corpus at `tools/experiments/_corpus.py`; `retrieval_failed` is TRUE on 0 of 14,006 checks, so no deferred run pollutes the denominator (peer 1e's survivorship objection, answered). |
| E-104 | 2026-08-20 | Is a claim-level verdict against retrieved evidence a defensible product, or is it already commoditised? 68 sourced pages. | **DONE — the verifier is not the moat.** Per-answer citation is commoditised: four rivals at $10–$14 per 1k grounded requests, Anthropic Citations at no surcharge. But **zero of thirteen major providers rule on a claim against retrieved evidence**; the verdict-shaped products that exist are Bedrock contextual grounding ($0.10/1k), Bedrock Automated Reasoning ($0.17/1k, against a formal policy not the open web) and Google Check Grounding ($0.00075/1k). Closest direct competitor WebCite at ~$0.16 per verification. The verification vendors are being absorbed — Arize→Dynatrace $915M (13 Aug 2026), Galileo→Cisco (9 Apr 2026), TruEra→Snowflake, Logically→administration. **What is defensible is the corpus, the declared standard of proof, the audit trail and the liability — not the model.** | Section 5 below carries the load-bearing entries. |
| E-106 | 2026-08-20 | Founder's question: can Groq's free tier serve as a fallback brain? Quotas read off `console.groq.com/docs/rate-limits` today, divided into E-103's measured prompt anatomy. | **PARTLY — it is a floor, not a drain.** `openai/gpt-oss-120b` free is 30 RPM / 1,000 RPD / **8,000 TPM** / **200,000 TPD**. Our check call is ~12,750 chars, so **8,000 TPM is smaller than two of our calls** and TPM binds long before RPM. Ceiling: **10-17 vets/day** today, **28-47/day** after the approved merge. That cannot drain a 224-row defer backlog or keep up with `batch_size` 15/tick. It CAN score the golden set that blocks E-001, and it takes A1 off zero for $0. | Section 8.7 below. Assumption: 4 chars/token, sensitivity run at 3 and 5. |

---

## 5. State of the art — what the field does that we do not

Researched 2026-08-20. Full reasoning in the session transcript; the load-bearing conclusions:

- **The moat's verdict step is the academic fact-verification task.** FEVER's
  `SUPPORTS / REFUTES / NOT ENOUGH INFO` maps one-to-one onto `supported / refuted / unverifiable`.
  We are treating a classification problem as a generation problem.
- **Purpose-built models beat frontier models at it, at a fraction of the size.**
  Bespoke-MiniCheck-7B tops the LLM-AggreFact leaderboard at 77.4%, above Claude 3.5 Sonnet.
  HHEM-2.1-Open scores 71.8% in under 600MB of RAM and about 1.5s per 2k tokens on an x86 CPU.
- **The best PERMISSIVELY-LICENSED verifier was never in E-101's sweep, and it beats GPT-4o.**
  IBM **Granite Guardian 3.3 (8B)** scores **76.5** on LLM-AggreFact under **Apache 2.0**, above
  GPT-4o at 75.9. The two models ranked above it are non-commercial (Bespoke-MiniCheck-7B, 77.4,
  CC BY-NC 4.0) and paid (Claude 3.5 Sonnet, 77.2). This does NOT overturn E-101 — E-101 measured
  on OUR pairs and killed Stage B on throughput, which an 8B model shares — but it does mean the
  honest statement is *"no free verifier we tested can rule"*, never *"no free verifier can rule"*.
  Closing that gap costs one run against a hosted Apache-2.0 endpoint, not new hardware.
- **The standard pipeline is document retrieval, then evidence selection, then verdict.**
  OpenFactCheck formalises it as `claim_processor -> retriever -> verifier`, YAML-configured.
  Loki (MIT) adds check-worthiness as an explicit stage, which the engine does not have.
- **Query expansion without a model is a solved classical problem.** RM3 pseudo-relevance
  feedback; doc2query at indexing time with BM25 retrieval unchanged.
- **Abstention is a measurable axis with its own benchmark.** AA-Omniscience scores -100..100 and
  applies no penalty for declining to answer, which is exactly the engine's rule.

## 6. Local facts this programme starts from

Measured on this machine 2026-08-20, not quoted from memory:

- `/usr/local/bin/ollama` is installed. The daemon is DOWN. Five models are already pulled:
  `gemma2`, `gemma3`, `llama3.2`, `nomic-embed-text`, `qwen2.5-coder`.
- Python is 3.14.6 on x86_64 and there is **no torch wheel**. Any local transformer must run
  behind the Ollama HTTP daemon, not as an in-process import.
- `prospector/prescreen_prefilter.py` already contains a working Ollama embedding backend, wired
  off. `telemetry.py:195` already prices ollama at $0.00.
- `run.py:605` records *"Ollama REJECTED 2026-07-01 (markdown, not JSON)"*. That rejection was of
  Ollama as a GENERALIST operator required to emit JSON, and it was correct. A purpose-built
  entailment classifier returns a score, not JSON. The rejection does not transfer.
- Model-free today: `kill_filter.py` (0 model references), `pricing.py` (0), `publish/publish.py`
  (0). `dedup.py` runs on difflib plus Jaccard, not embeddings.

## 7. Traps already paid for — do not re-find these

- A sleep profiler attributes background daemon threads to the span that happens to be open.
  Get the number from the thing measured. (peer `prospector-20`, 2026-08-20)
- `pytest` exits 0 when it collects nothing. Wrong path, three greens, no signal.
- A mutation test that anchors on a non-unique string mutates the wrong site and reads green.
- `store/` is live state. `setup_worktree.sh` copy-on-write clones it, so this worktree has its
  own `store/dossiers` (2931), `store/listings` (119), `store/runs` (17), `store/golden_runs` (77).
- Production's store is on Fly at `/data/store`, not on this laptop. A laptop process resolving
  `config.store_root()` reads a copy that stopped updating at the cutover.

---

# CORRECTION, same day: this estate already has an experiment programme

Written after section 3 and before any experiment was run. **Sections 3 and 4 above are superseded
by this section.** Leaving them in place, because a backlog written in ignorance of prior art is
the exact failure this correction records, and deleting it would hide that.

## What I found

`tools/experiments/` holds about twenty completed experiments with JSON receipts and written
conclusions, driven by `tools/experiments/runner.py`, and registered in
**`docs/COMMERCIAL_READINESS_PROGRAM.md` §14**. That is the estate's experiment ledger. It already
exists, it has a harness, and it has a registration convention.

**So E-002 is cancelled: the harness I was about to build is already built.** And this programme
does not open a second ledger. New experiments are registered in
`docs/COMMERCIAL_READINESS_PROGRAM.md` §14 alongside the existing ones. Two ledgers for one class
of work is worse than none: both accumulate rows, neither is complete, and no session can tell
which is authoritative.

## What the prior experiments already measured

| Prior | Finding | What it does to my backlog |
|---|---|---|
| **E15** (2026-08-07) | **Rationale-infidelity 48.9%** (171/350, 95% CI 43.7-54.1) at tau=0.0691. Nearly half the moat's ruled checks write a rationale their own cited passage does not entail. | This IS the A7 baseline. A7 is no longer "NOT MEASURED". Target: drive 48.9% toward 0. |
| **E17** (2026-08-07) | HHEM vs moat verdicts: **AUC 0.673**, agreement supported 52.8% (n=182), refuted 71.0% (n=38), unverifiable 67.6% (n=380). | **Substantially weakens E-010.** 0.673 is weak separation. HHEM alone is NOT a drop-in verdict replacement. E-010 must be reframed as a cascade screen, not a substitute. |
| **E17** | **"MiniCheck: SKIPPED — no local copy; no model was downloaded."** | This arm is genuinely OPEN, and it is now the highest-value cheap experiment. MiniCheck scores 77.4% on LLM-AggreFact against HHEM's 71.8%. |
| **E16** | Rerank ceiling probe over already-stored passages, zero LLM, zero network. | E-043 has prior art. Read E16's receipts before proposing a reranker. |
| **E3** | Concurrency knee at n=8, cross-talk 0, but **50 bad calls out of 132 (37.9%)**. | E-020/E-030 have prior art for CLI-level concurrency ACROSS candidates. Still open: concurrency across the six checks WITHIN one candidate. Different question. |
| **§18** | 35.8% of August kills lost to grounding QUALITY, on candidates carrying a mean 21.4 citations. | Confirms memory `grounding-bottleneck-is-relevance-not-availability`. E-042 is well-founded. |

## Two corrections to things I stated earlier today

1. **I said a local transformer "must go over the Ollama HTTP daemon" because there is no cp314
   torch wheel.** The constraint is real; the conclusion was wrong. This estate already solved it
   with a **sidecar interpreter**: `tools/experiments/_hhem_sidecar.py` runs under a separate
   python3.12 carrying torch 2.2.2 and transformers 4.57.6, file-in/file-out rather than
   stdin/stdout, because torch and transformers write progress bars to whichever stream they
   like and a JSON payload sharing stdout with a warning is a parse error waiting to happen.
   HHEM is a 184M-parameter local cross-encoder: zero network, zero tokens, zero paid calls.

2. **I proposed HHEM as the availability fix on benchmark scores alone.** This estate had already
   measured it against our own corpus and got AUC 0.673. A public leaderboard number is a claim
   about someone else's dataset. E17 is the claim about ours, and it is much less flattering.

## A live defect found while reading this

`_hhem_sidecar.py` documents its interpreter as `/tmp/prospector-ml-venv/bin/python3.12`.
**`/tmp` has since been cleared and that venv is gone.** So every HHEM experiment's published
receipt line — *"reproduce with `.venv/bin/python tools/experiments/runner.py run E15 --limit 350`"* —
is false as of 2026-08-20. It does not error informatively; the sidecar interpreter simply is not
there.

The model itself survived: `~/.cache/huggingface/hub/models--vectara--hallucination_evaluation_model`
is still present, so only the interpreter needs rebuilding.

**The class: a reproducibility claim whose dependency lives in a directory the OS empties.** The
fix is not to rebuild it in `/tmp` again. Rebuilding at
`~/.local/share/prospector-ml-venv`, and the sidecar's path resolution needs to follow.

## The revised, honest backlog

Ordered by expected value now that prior art is accounted for.

| ID | Experiment | Why it is worth running | Status |
|---|---|---|---|
| **E-100** | Move the ML sidecar out of `/tmp` and make `runner.py`'s reproduce-line true again. Add a check that fails when the sidecar interpreter is missing, rather than failing obscurely. | Every other local-model experiment is blocked on this, and the estate currently publishes a reproduce command that does not work. | IN PROGRESS |
| **E-101** | **MiniCheck vs HHEM on OUR corpus**, same method as E17 so the numbers are comparable: AUC against moat verdicts, agreement per verdict class. Refuting outcome stated up front: if MiniCheck's AUC is not materially above HHEM's 0.673, the local-classifier route is dead for verdicts and only survives as a cascade screen. | E17 explicitly skipped it. It is the single open question with the largest consequence, and it costs no API money. | READY |
| **E-102** | Re-run E15 to get a current A7 baseline on today's corpus, and record the corpus fingerprint. | The 48.9% is from 2026-08-07 and the store is live. A programme measuring improvement needs today's number, not a fortnight-old one. | READY, blocked on E-100 |
| **E-103** | Concurrency across the six checks WITHIN one candidate, with kill-fast retained as a cancel rather than a gate. E3 measured concurrency across candidates; this is a different axis and it is the direct p50 win. | Kill-fast is a cost optimisation, and wasted calls are an OPERATIONAL cost, so wish 14 makes the trade explicit rather than free: the p50 win has to be worth the calls thrown away. Post the estimate before the run. | READY |
| **E-104** | Golden set with resolution. Still the blocker for every quality claim: 1.00 on 9 items measures nothing. | Unchanged by prior art. | READY |
| **E-105** | Roster breadth for availability: Cohere Command A+ (14.2% AA-Omniscience hallucination rate vs MiniMax M3's 18.4%) on the golden set. | A1 is 0% today. This is the only untested hosted model worth the run. | BLOCKED on E-104 |

Everything else from section 3 stays in the pool but is not scheduled until these six resolve.

---

## E-100 — RESOLVED 2026-08-20. The instrument is durable, and a test now says so.

**Claim tested:** every published HHEM receipt ends with a reproduce command that no longer works,
because the interpreter it shells out to lived in `/tmp` and macOS emptied `/tmp`.

**Confirmed, then fixed.** The sidecar was rebuilt at `~/.local/share/prospector-ml-venv`
(python3.12.8, torch 2.2.2, transformers 4.57.6) and `_hhem.py` now resolves there.
`~/.cache/huggingface/hub/models--vectara--hallucination_evaluation_model` had survived, so only
the interpreter needed rebuilding.

**Proof the instrument works end to end**, four hand-built pairs through the real sidecar:

| premise → hypothesis | HHEM score | expected |
|---|---|---|
| Eiffel Tower in Paris, 1889 → "located in Paris" | **0.868** | high |
| same premise → "located in Berlin" | **0.0038** | low |
| Acme revenue 4.2M Q3 → identical sentence | **0.918** | high |
| Lagos rainfall → "bananas are a source of potassium" | **0.0011** | low |

`load_seconds 3.78`, `predict_seconds 2.96`, `torch_threads 12`, python 3.12.8. Reproduce:

```
HF_HUB_OFFLINE=1 ~/.local/share/prospector-ml-venv/bin/python \
  tools/experiments/_hhem_sidecar.py <in.json> <out.json>
```

**A prohibition in the source was measured and found wrong.** `_hhem.py:12` read *"NEVER
pip-install into the sidecar. A previous `numpy<2` pin broke transformers there outright."* On this
rebuild `numpy<2` was **required**: torch 2.2.2 is compiled against the numpy 1.x C API and emits
`Failed to initialize NumPy: _ARRAY_API not found` under numpy 2.x. With numpy 1.26.4 installed,
transformers 4.57.6 imports and HHEM scores correctly, as the table above shows. The docstring now
records the measurement instead of the folklore. I walked into that prohibition before reading it,
which is the reason it is written down precisely rather than restated.

**The class, and the guard that closes it.** The class is *a published measurement whose instrument
is stored somewhere the OS empties*. A rebuild alone does not close it — the same default would rot
again the next time. `tests/unit/test_experiment_sidecar_path.py` (7 tests) fails if any file under
`tools/experiments/` names a venv or interpreter under `/tmp`, if the preferred sidecar path is not
under `$HOME`, or if a missing sidecar stops raising instead of degrading silently.

Mutation-proved, not merely green:

| mutation | result |
|---|---|
| preferred sidecar path put back under `/tmp` | **2 RED** — `test_sidecar_default_is_not_ephemeral`, `test_no_experiment_stores_a_durable_venv_under_tmp` |
| `require_sidecar` no longer raises when the interpreter is absent | **1 RED** — `test_a_missing_sidecar_raises_rather_than_degrading` |
| restored | **7 passed** |

The `/tmp` location is deliberately not kept as a fallback candidate: it is the exact thing the
guard forbids. Anyone who still has a sidecar there points at it with `PROSPECTOR_ML_PYTHON`.

---

## E-101 — the verifier arm sweep. Design, instrument, and what is still running.

**The question.** The moat spends a paid model call on every check of every candidate. E-101 asks
whether a local model can rule the same verdicts, and it answers with a ranking rather than a
recommendation: score every credible open verifier on the same frozen pairs and report AUC against
the moat's own decisions, plus seconds per pair.

**Why it is a SWEEP and not a comparison.** The first version of this experiment was MiniCheck
against HHEM, two arms. The founder rejected that scope: *"you have wide berth so i need a 60
picture"* and *"all options needs o be ehausetd truly"*. Two arms cannot say whether the best
available verifier was tried; they can only say which of two happened to be picked. The registry is
now 13 arms in `tools/experiments/_verifiers.py`, spanning six families, three lexical baselines
included so that any neural arm which fails to beat string overlap is visible as such.

### The six families, and why the count is six

A family is a scoring CONTRACT, not a model. Two models share a family when the same code produces
their score. Six is what the 13 arms actually need:

| family | how a score is produced | arms |
|---|---|---|
| `lexical` | token / 3-gram / number overlap, no model | 3 |
| `nli-entailment` | softmax over 3 NLI labels, take the entailment index | 3 |
| `seqclass-minicheck` | sequence-classification head, positive-class probability | 2 |
| `seq2seq-minicheck` | decoder's first-token probability of "1" | 1 |
| `hhem-custom` | Vectara's own remote-code head | 1 |
| `causal-minicheck` / `causal-judge` | next-token distribution at the LAST position | 2 |

### The trap that decides whether the causal arms mean anything

Both 7B/8B arms read the next-token distribution at the last position of the sequence. The
tokenizer's default padding side is RIGHT. Under right padding, every sequence in a batch that is
not the longest ends in pad tokens, so "the last position" is a pad token and the score becomes the
model's opinion about padding.

This failure has no symptom. It does not raise. It produces numbers in [0, 1] that look like
scores. A weak AUC produced this way reads as *"the local model disagrees with the moat"* — which is
the exact finding the experiment exists to measure. It would have been published as a result.

`tools/experiments/_prove_causal_wiring.py` closes it by scoring the same pairs at batch_size 1 and
batch_size 8 and requiring agreement. At batch_size 1 there is no padding, so the two agree only if
padding is not being read. It runs on `hf-internal-testing/tiny-random-LlamaForCausalLM`, so the
wiring is proved without downloading 31 GB of weights.

**The first version of that check was half vacuous, and the measurement says so.** Flipping
`padding_side` back to `"right"` and re-running produced:

| family | divergence with the bug present | caught by a 1e-4 tolerance? |
|---|---|---|
| `causal-judge` | 3.37e-03 | yes |
| `causal-minicheck` | 2.01e-05 | **no — passed green with the bug** |

Correct float non-determinism between batch sizes, measured on the same runs, was 1.46e-11 and
5.96e-08. So the two populations are separated, and 1e-6 sits between them with more than an order
of magnitude of margin on each side. The tolerance is now 1e-6, chosen from those four numbers.

A tolerance alone is still a judgement about float behaviour, and the tiny random model is not the
7B one, so a second check asserts `padding_side == "left"` structurally. Re-mutating turns **4
checks red across both families**; reverted, **17 pass**.

The general lesson, which is not specific to padding: **a mutation test can be vacuous for one
member of a family and sound for another.** Proving a guard by mutating it once, on one arm, proves
it for that arm only.

### Three deviations from the published references, recorded rather than hidden

The prompts are verbatim from their sources, fetched 2026-08-20 — MiniCheck's `SYSTEM_PROMPT` and
`USER_PROMPT` from the repo's `utils.py`, Lynx's evaluation template from its model card. The
wording is part of the instrument: these models were tuned against those exact strings, so an
improved prompt measures a different model. Where this implementation departs, it says so:

1. **Bespoke's aggregation.** The reference sums `exp(logprob)` over vLLM's top-k decoded tokens.
   This runs plain transformers and sums the full softmax over every token id that decodes to
   "yes" — the same quantity computed exactly rather than truncated at k. Several ids spell one
   word, so picking a single id would drop the rest.
2. **Sentence splitting.** nltk Punkt is replaced by a regex. `n_multi_sentence` is reported so the
   size of the difference is measured rather than argued: it counts how often the reference's
   min-over-sentences reduction had more than one sentence to reduce.
3. **Lynx is crippled deliberately, and its number is a floor.** Lynx is a generative judge: it
   writes REASONING first and reaches SCORE about 600 tokens in. Generating that for 3,472 pairs on
   CPU is not affordable, so the JSON prefix is teacher-forced and the PASS/FAIL choice is read at
   the next position. **This removes the model's chain of thought.** A weak AUC from this arm is a
   LOWER BOUND on Lynx and must never be reported as Lynx's score.

### Where each arm runs, and why the split is by FILE FORMAT

The obvious split is by size — small models on the laptop, large ones on rented compute. That is
the wrong axis. The real constraint is the checkpoint format:

- transformers refuses `torch.load` on `.bin` (pickle) checkpoints unless torch >= 2.6
  (CVE-2025-32434).
- macOS x86_64 caps at torch 2.2.2; torch dropped that platform afterwards.
- Therefore **no pickle checkpoint can load on this laptop at any size**, and a small pickle model
  must go to the rented host while a larger safetensors one need not.

Confirmed this segment rather than reasoned: `minicheck-rob` is a pickle checkpoint, it loaded and
scored on Fly's torch 2.13, and it cannot load here.

Loading a pickle checkpoint executes arbitrary code. That is a second, independent reason the
pickle arms run on the disposable rented host and never on the laptop that holds estate
credentials.

### The lab

`prospector-verifier-lab`, machine `84514eb2d75578`, performance-16x (16 cores / 32768 MB), volume
`vol_r7y20z8d1zokql3r` 60 GB at `/data`, region lhr. **It is rented for this experiment and must be
destroyed when the sweep ends.**

**GPU is not available and that is a measured fact, not an assumption.** `fly` v0.4.85 exposes zero
GPU flags on `machine run` or `machine create`, and `fly platform vm-sizes` lists no GPU tier for
this organisation. Stage B therefore has to be affordable on CPU or not happen.

### The comparability risk, removed rather than bounded

The Fly image arrived with transformers 5.15.1 against the laptop's 4.57.6. The tempting move is to
quantify the gap. The cheaper and stronger move is to delete it: `transformers==4.57.6` was
installed on Fly, giving **torch 2.13.0+cpu / transformers 4.57.6 / numpy 2.5.2** — a pickle-capable
torch with the laptop's exact transformers.

That pin was not a precaution. transformers 5.15.1 **breaks HHEM outright**, and breaks it in the
worse of the two available ways:

```
hhem FAIL AttributeError 'HHEMv2ForSequenceClassification' object has no attribute 'all_tied_weights_keys'
HHEMv2ForSequenceClassification LOAD REPORT from: vectara/hallucination_evaluation_model
Key                                        | Status  |
t5.transformer.encoder.embed_tokens.weight | MISSING |
- MISSING: those params were newly initialized because missing from the checkpoint.
```

The exception is the lucky half. The load report is the dangerous half: a remote-code model can
silently produce a DIFFERENT model — here with a newly initialised embedding table — rather than an
error. Under a version that raised slightly later, this would have scored.

### The cross-host control, which costs nothing extra

Four arms — `hhem`, `nli-fever-bs`, `nli-fever-lg`, `vitaminc` — are scored on BOTH hosts against
the identical frozen pair order. Agreement on those four is the evidence that the two hosts are one
instrument. The smoke values already recorded for the first indices:

| arm | Fly, first 4 pairs |
|---|---|
| `hhem` | `[0.0324, 0.0215, 0.0443, 0.0478]` |
| `nli-mnli-lg` | `[0.0643, 0.0229, 0.0704, 0.0740]` (entailment idx 2) |
| `minicheck-rob` | `[0.0724, 0.0106, 0.1780, 0.2076]` |
| `minicheck-deb` | `[0.0171, 0.0135, 0.0811, 0.0888]` |
| `minicheck-t5` | `[0.0215, 0.0275, 0.1922, 0.5400]` |
| `nli-fever-bs` | `[0.0133, 0.0231, 0.7420, 0.7150]` (entailment idx 0) |

The entailment index is resolved BY LABEL NAME from the model config, never by position, and the
two live values above prove why: `microsoft/deberta-large-mnli` puts entailment at index 2 and
`MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` puts it at index 0. A hardcoded index would have
inverted one of the two silently.

**Scoring is split across hosts; ANALYSIS is not.** Fly produces score vectors only. Every AUC is
computed by one implementation on the laptop via `--scores-from`, so no cross-host difference can
enter through two copies of the metric code.

### Status at the time of writing — not yet a result

| where | state |
|---|---|
| Fly Stage A, 8 encoder arms | RUNNING, sequential, on arm 1 of 8 (`minicheck-t5`), load 14.15 of 16 cores |
| laptop sweep | RUNNING, 3 lexical arms done, `hhem` in flight at 48 min and 414% CPU |
| lexical baselines | `lex-token` 0.4 s / 8222 pairs·s⁻¹, `lex-3gram` 1.6 s / 2132, `lex-number` 0.4 s / 7835 |
| Bespoke-7B weights | downloaded to Fly, 15 GB in 2 m 19 s, `/data` at 54% with 27 GB free |
| Stage B (7B/8B) | code complete and wiring-proved; BLOCKED on CPU throughput being measured |

**Stage B's throughput probe is deliberately not running yet.** Seconds-per-pair is a published
column of the Stage A table. Starting a 7B forward pass on the same 16 cores would inflate the
timing of every remaining Stage A arm, so the probe waits for Stage A to finish rather than
corrupting the numbers it is waiting for. Both dtypes will then be measured via `VERIFIER_DTYPE`,
because torch routes bfloat16 through oneDNN — fast on hardware with AVX512-BF16, slower than
float32 on hardware without it — and which one this host is cannot be assumed.

### The gate this work committed through, and why it was ungated

The POPDD pre-commit gate is absent from this repo's `.git/hooks`: the hook body is tracked and
intact, but the symlink died with the `.git` admin directory at 07:35. It was deliberately NOT
restored. Under the repo venv it produced no output and hit a 300 s timeout, and
`popdd_verify.py:432` records that this hook holds `.git/index.lock` for its entire runtime.
Restoring it today would wedge every commit in every worktree rather than gate them. Three other
hooks lost in the same wipe — graphify's `post-commit` and `post-checkout`, and the `pre-push`
shim — WERE restored, and `graphify_sweep.py --check-hooks` now reports all triggers present.

---

# 8. Progress notes — 2026-08-20 synthesis

Written because the standing instruction is rigorous, careful documentation, and a programme with
no written position is a programme that restarts from zero at every compaction. This section is
the answer to four founder questions asked in one message: what have we done, where are we, what
is the next set of actions, and is anything promising.

## 8.1 Where the engine actually is, in numbers

| Thing | Number | How it was read |
|---|---|---|
| A1 availability | **0%** | The `prospector-engine` box logs `moat_blind` every tick and retries in 300s. No trusted brain can be reached from it. |
| A2, A3a, A3b, A5, A7, A8 | **no baseline** | Section 1. Five of nine axes have no unit reading at all, so a 1000x claim on them is not falsifiable. |
| A4 discrimination | **1.00 on 9 items** | Saturated. Cannot register a gain or a regression. |
| A6 cost | ~$3.60 / 1000 verdicts | Estimate, not a meter reading. |
| Verdict brains reachable | **1, and it is the laptop** | `out=$(timeout 120 claude -p "Reply with exactly the word: ok" 2>&1); rc=$?` → rc=0, output `ok`. |
| Dossiers in the canonical store | **0**, ledger 21 lines | `config.store_root()` resolves to `/Users/chidionyema/Documents/code/prospector/store`. |
| Dossiers on the live volume | **3,622** | Fly volume `/data`. `/dev/vdc` ext4 is the only persistent mount; `/app/config.yaml` is in the IMAGE and does not survive a deploy. |
| Money rail | **serving** | mumchimp.com, the catalogue and the Stripe rail all answer 200. |

The one-line statement of the position: **the shop sells and the engine produces nothing to sell.**

## 8.2 The two things that block everything else

**A1 is the fire.** Nothing in this programme can be measured on a machine that cannot rule. The
fix is known and is not research: the Claude login on the `prospector-engine` box, or MiniMax
credits. Both are the founder's — one is an identity, the other is money leaving the account.
E-011 (roster breadth) and E-012 (multiple keys rotated on 429) are the engineering half and can
be built now.

**A4 is the instrument.** Discrimination 1.00 on nine items grades nothing, so E-040 through E-045
— ensemble, adversarial-on-every-PASS, retrieval-is-the-bottleneck, cross-encoder reranker,
generalised literal-anchor rule, calibration — are **unrunnable rather than merely unrun**. E-001
builds a golden set with resolution. It costs no money, and the corpus already holds 2,929
dossiers to draw hard negatives from. **E-001 is the highest-value item on this list that needs
nobody's permission.**

Two golden gates exist and they are not interchangeable. `tests/test_golden_set.py:163` uses
`MockOperator` (`:171`) and asserts `discrimination == 1.0` (`:189`) — free, no brain, runs today.
The live one is `prospector/golden.py` via `run.py:4403 --deep`, floor 0.75 at `:4405`, and
`run.py:3602` records that it runs against FIXED evidence (`fixtures/golden_fixtures.json`) — so
it is nine candidates of model calls with no retrieval, not a full pipeline run.

## 8.3 What is promising, ranked, with what each one needs

| Rank | Item | Effect | Needs |
|---|---|---|---|
| 1 | E-011 roster breadth, E-012 key rotation | A1: 0% → serving | money or a login; the code is ours |
| 2 | **E-001 golden set with resolution** | unblocks E-040..E-045 | **nothing** |
| 3 | Merge six verdict calls into one (E-103, founder-approved) | A6 and A3: 2.8x tokens, 4.679x calls | a brain only to ship |
| 4 | E-023 provider prompt caching | same waste, stacks with rank 3 | nothing new |
| 5 | Retrieval as the quality ceiling (E-042, E-043) | A7 and A5 | blocked on E-001 |
| 6 | E-102 re-measure rationale infidelity | the product itself | a live brain |

Rank 5 deserves its own sentence, because it is the finding most likely to change what we build.
**73.3% of all 14,006 checks come back `unverifiable`** and only 4.7% come back `refuted`. The
engine is not being wrong; it is failing to find evidence. Every hour spent on a better verdict
model is aimed at 22.0% of the traffic.

Rank 6 is the commercially important one. E15 measured **48.9% rationale infidelity** (171/350,
CI 43.7–54.1): nearly half the moat's ruled checks write a rationale their own cited passage does
not entail. E-104 says the audit trail is the asset. A 48.9% infidelity rate is a defect in the
asset, and it also confounds every moat-agreement number we quote — which is exactly why E-101
needed its second, construction-labelled angle.

## 8.4 Research still outstanding

1. **Packaging, pricing and defensibility for a one-operator research product.** Never launched —
   it hit the agent fleet cap. E-104 turned this into the important question: if the corpus and
   the standard of proof are the asset, what is the sellable object and what does it cost?
2. **Do the cheap hosted graders beat our own moat on our own corpus?** Bedrock contextual
   grounding at $0.10/1k and Google Check Grounding at $0.00075/1k both score a claim against
   supplied passages. Running them over E-101's frozen pair set re-tests E-101's question with
   models E-101 could not run, as a one-off spend of a few dollars. Cost estimate goes in this
   file before it runs (wish 14).
3. **Granite Guardian 3.3 (Apache 2.0, 76.5) on our pairs.** The laptop cannot host it — Python
   3.14.6 x86_64 has no torch wheel, so anything local must sit behind the Ollama daemon, which is
   down. A hosted endpoint answers it without buying hardware.
4. **Do Groq's free-tier terms allow our candidate text?** E-106 (§8.7) answered the capacity
   half of the founder's question from published quotas. The half that is not arithmetic is
   whether free-tier traffic is retained or used for training. E-104's finding is that **the
   corpus and the audit trail are the asset, not the model**, so posting candidate text and
   retrieved passages to a free tier is a business decision about the asset, not a technical one.
   It is the founder's call and it is the only thing blocking the wiring. The quotas page does
   not answer it; it needs Groq's terms of service read directly.
5. **Who buys a claim-level verdict with consequences attached** — pharma review, advertising
   substantiation, ESG. E-104 found no per-verdict product priced for a business carrying
   liability. That is either an opening or the reason nobody bothered, and the two look identical
   from outside.

## 8.5 Design constraints on the approved merge, recorded before it is built

The founder approved merging the six check calls into one at the corrected 2.8x. Five constraints
came out of the peer review of that plan and must survive into the implementation:

1. **Parse the merged reply per check.** One bad parse must not defer a whole candidate onto a
   drain that is already stuck. A per-check parse failure degrades that check, not the vet.
2. **Kill-fast must still short-circuit.** Merging removes the ability to stop after check 2. At
   4.7% `refuted` the loss is small, but it is a loss and it must be measured, not assumed away.
3. **Ship behind the mock gate first** (`tests/test_golden_set.py`, no brain required), and land
   only after the live nine-item run clears.
4. **The merged prompt must not exceed the model's context on the long tail.** Candidate JSON has
   a median of 4,220 chars and a mean of 19,756 — the mean is 4.7x the median, so the tail is real.
5. **Provider-agnostic.** `moat_primary` is `[minimax, claude_cli]`; the merge must not assume one
   provider's JSON behaviour, or it becomes a reason the roster cannot widen, which is rank 1.

## 8.6 Corrections made today, recorded so they are not re-made

- **"Up to 6x" on the merge was wrong.** Measured 2.8x on tokens, 4.679x on calls. Corrected to
  the founder unprompted; he shipped it anyway.
- **"No brain is available" was wrong**, and it was the founder's own belief. The laptop's
  `claude -p` answers. The Fly box is the blind one. The distinction decides where work can run.
- **A padding bug I reported in Stage B did not exist.** `e101_stageB_fly.py:183` already sets
  `padding_side = "left"`. One angle, carefully done, and wrong; the second angle took four
  minutes and would have prevented a false claim reaching the founder.
- **`cmd | tail` reports tail's exit status.** It bit this session again on a brain probe that
  printed nothing and reported `exit=0`. Capture the status before any pipe.

## 8.7 E-106 — Groq's free tier as a fallback brain

Founder's question, 2026-08-20: *"as part of research outstanding can we use groq free tier as
fallback"*. Groq was already named in E-011 as roster breadth, but nobody had put a number on it.

**The answer is: yes as a floor, no as a drain.** It cannot carry the backlog. It can take A1 off
zero and it can score the golden set that blocks everything else, and it costs nothing.

### The quotas, read off the source

From `https://console.groq.com/docs/rate-limits`, fetched 2026-08-20. Free plan:

| Model | RPM | RPD | TPM | TPD |
|---|---|---|---|---|
| `openai/gpt-oss-120b` | 30 | 1,000 | **8,000** | **200,000** |
| `openai/gpt-oss-20b` | 30 | 1,000 | 8,000 | 200,000 |
| `qwen/qwen3.6-27b` | 30 | 1,000 | 8,000 | 200,000 |
| `groq/compound` | 30 | **250** | **70,000** | not listed |
| `groq/compound-mini` | 30 | 250 | 70,000 | not listed |

### What that is worth against our own measured call

E-103 measured the call, so this is division rather than estimation. One check call is ~11,250
chars of fixed preamble plus ~1,500 chars of evidence = **~12,750 chars ≈ 3,188 tokens**. A vet
is 4.679 paid calls. The approved merge takes a whole vet to ~21,450 chars ≈ 5,363 tokens.

| | today, six calls | after the merge |
|---|---|---|
| calls that fit in 8,000 TPM | **2 per minute** | 1 per minute |
| calls in 200,000 TPD | 62 | 37 |
| **vets per day** | **13.4** | **37.3** |

**TPM is the binding constraint and RPM never binds.** 30 requests a minute is generous; 8,000
tokens a minute is smaller than three of our calls. Anyone reading the RPM column alone concludes
this tier is ten times more useful than it is.

**Sensitivity.** The one soft link is 4 chars per token. At 3 the answer is 10.1 vets/day and 28.0
merged; at 5 it is 16.8 and 46.6. **10-17 today, 28-47 merged**, and the verdict does not change
anywhere in that range. Replace the assumption with a measurement by tokenising a real prompt
rather than by arguing about the ratio.

### Why that is not a drain

`schedule.batch_size` is 15 candidates per tick and the defer backlog is 224 rows. At 13 vets a
day the free tier is behind generation from the first tick and would take about seventeen days to
clear the backlog it starts with. It is not the answer to A2.

### Why it is still worth wiring

1. **A1 is measured at 0%.** Sixty-two trusted-fence-safe calls a day for nothing is not a small
   number when the current number is zero. The engine currently produces nothing at all.
2. **It scores E-001, which blocks every quality experiment.** The nine-item set costs ~28,700
   tokens, 14% of one day's allowance. A 100-item replacement costs ~319,000 tokens, so it runs
   over two days at no cost. E-001 needs a brain exactly once, to score a set it does not need a
   brain to build.
3. **The fence already exists and needs no promotion.** Groq would sit outside `moat_primary()`,
   so `is_provisional_provider` (`operator.py:1451`) stamps anything it rules `provisional`, and
   `run.py:864` bars publication on PASS. Adding it is a config line and an adapter, not a
   golden-gate promotion. It is the same shape the estate already supports for DeepSeek.

### Two traps to record before anyone builds it

**`groq/compound` looks like the better model and is the wrong one.** Its 70,000 TPM is 8.75x the
binding constraint, which makes it tempting. It is an agentic system with **built-in web search**,
and this engine's first rule is verdict-from-retrieval-only: the model rules on passages *we*
fetched, and silence is `unverifiable`. A model that can search on its own breaks the provenance
the whole product is built on. If it is ever used, its own search must be provably off, and
proving that is more work than the extra quota is worth.

**Free-tier terms are a business decision, not a technical one.** See §8.4 item 4. Not wired until
the founder rules.

### The cost estimate, before anything runs (wish 14)

**$0.00.** No card, no rented box, no operational line. The paid Groq tier is money and therefore
the founder's, and this experiment is designed so that the free tier answers it without reaching
that question. If the free tier proves useful, the paid tier's price becomes a separate ticket
with its own estimate.

---

## 9. Engagement — the axis the engine does not have

Founder, 2026-08-21: *"what is the idea generation lacking to psh it to the next level of
enganenent, in talking dragon den, sharktank level of ideas"*, *"we need engagent as well as
viablity"*, *"for sales"*.

### 9.0 The headline number, and the control that decides it

**100.0% of the 64 ideas the engine has ever passed match the title frame `<X> for <buyer>`.
Across all 2,044 verdict dossiers, 21.2% do.**

**CORRECTION 2026-08-21, before you read the number as causal. The 100% is SPECIFIED, not
selected.** A peer asked whether the PASS titles came from the same generation config as the other
2,044. They do not. `prompts/retitle.md` mandates that exact frame in writing — *"title — what the
business does, and who pays for it: `<what the business does> for <who pays>`. Both halves,
always."* It reaches PASS dossiers on two paths and neither one touches a KILL:

1. `tools/retitle_catalogue.py:394 _write_dossier_title` writes `candidate.title` into
   `store/dossiers/<id>.pass.json`, so a republish preserves it (`tools/retitle_catalogue.py:52`).
2. `prospector/field_write.py:143 _propose_title` renders the same `retitle` prompt in-engine
   whenever the register linter breaches a title.

So "100% of PASSes carry the frame" is a prompt instruction observed working. It is **not**
evidence that the scoring filter rewards one shape, and the null control above cannot separate the
two, because the null is drawn from titles the retitle prompt never saw.

**What survives the correction, and is now the headline: the KILL-only drift.** KILL dossiers never
reach `retitle.md`, so their frame rate is generation's own. It is rising with nothing telling it
to:

| month | KILL dossiers | carry `<X> for <buyer>` |
|---|---:|---:|
| 2026-06 | 724 | 8.6% |
| 2026-07 | 220 | 16.4% |
| 2026-08 | 1,032 | **25.9%** |

A 3.0x rise in two months, on the population no prompt is steering. The August weekly figures
(40.5 / 22.1 / 40.0) are noisy and must not be read as a within-month trend.

A raw rate on 64 items decides nothing by itself, so it was run against a null: 2,000 random
subsamples of size 64 drawn from the same 2,044 titles, fixed seed. Reproduce with
`scratchpad/measure_template.py`.

| property | PASS (n=64) | ALL (n=2,044) | null p5 | null p95 | verdict |
|---|---:|---:|---:|---:|---|
| `<X> for <buyer>` frame | **100.0%** | 21.2% | 12.5% | 29.7% | **outside null — 0 of 2,000 draws reached it** |
| names a jurisdiction | **43.8%** | 13.2% | 6.2% | 20.3% | **outside null — 0 of 2,000 draws reached it** |
| <= 8 words | **71.9%** | 49.9% | 39.1% | 60.9% | **outside null — 0 of 2,000 draws reached it** |
| contains a digit | 1.6% | 3.2% | 0.0% | 7.8% | inside null — no effect |

Corpus: 2,044 verdict dossiers, 1,976 kill / 64 pass / 4 defer, a 3.1% pass rate. **Do not copy
the worktree path this was first read from — `prospector-ship-wt` no longer exists.** `store/` is
tracked runtime state cloned into every worktree, so any literal path rots; resolve it with
`config.store_root()`. Re-measured 2026-08-21 in a clone carrying the current corpus: 2,929
dossier files, 2,698 kill / 108 pass / 0 defer.

Every survivor is a narrow admin-friction arbitrage: "Dropped kerb application service for car
owners", "Council Tax exemption claims for dementia carers", "Bin store recycling signs for small
flat landlords". All viable. None is a business a Dragon leans forward for.

### 9.0b The claim the same control KILLED — recorded so it is not re-made

I first wrote that "generation produces variety and the filter selects a monoculture". Run against
the same null, that is **false as a statement about diversity**. Four lexical-diversity metrics on
the 64 PASSes all land INSIDE the null distribution for n=64 (`scratchpad/measure_diversity.py`):

| metric | PASS | null p5 | null p95 | percentile |
|---|---:|---:|---:|---:|
| distinct-1 | 0.7034 | 0.7018 | 0.7743 | 5.8% |
| distinct-2 | 0.9569 | 0.9460 | 0.9846 | 18.6% |
| opening-word entropy | 0.9844 | 0.9792 | 1.0000 | 9.8% |
| mean pairwise Jaccard | 0.0160 | 0.0091 | 0.0176 | 88.2% |

**The survivors are as lexically varied as any random 64 from the corpus. They are identical in
FORM.** That is a sharper finding than the one it replaces, and it changes the fix: vocabulary
diversity is not the problem and more diverse generation will not help. Read the correction in
9.0 before attributing the shared form to the scoring filter — the PASS titles were rewritten to
that form by `prompts/retitle.md`, so this table measures a corpus the prompt has already touched.
The claim that survives is about generation, not selection, and it is the KILL-only drift.

### 9.1 Why — three angles that agree

**Angle 1, structural. Twelve measurement points, none about desirability.** Six kill checks
(pain_reality, value_durability, incumbency, payer_solvency, distribution, legality); six score
axes (`prospector/models.py:114`); six weights summing to 1.00 (`config.yaml:850-855`).
`rg -i 'engag|novelty|surpris|compelling'` over `score.py`, `kill_filter.py` and `models.py`
returns one hit, and it is the word "engaged" in an unrelated comment.

**Angle 2, steering. The loop is closed.** `config.yaml:1521` aims the generation controller at
`target_qualities: [acute_pain, solvent_motivated_payer, durable_hard_core, real_distribution,
clean_legality, high_automatability]` — the same six qualities the filter grades. Nothing anywhere
asks for an idea that is interesting.

**Angle 3, outcome. The ambitious lane is wiped out.** `config.yaml:1515` records
*"venture is at 0 PASS in 35"*. An independent count over the dossier store gives `venture` 97.9%
of scored candidates below their own threshold (n=47) against `side_hustle` 42.5% (n=120).
`config.yaml:1523` records `min_composite` as the modal kill gate in **8 of 9 persona cells**:
candidates clear the hard evidence gates and then die on the score.

### 9.2 Why a weight will not fix it

The filter is grounded-evidence-only, so a candidate's score rises with how much prior art exists
to cite. A genuinely novel idea retrieves thin, returns `unverifiable` (73.3% of 14,006 checks
already do), and dies. A crowded, obvious, well-documented idea retrieves cleanly and passes.
**The selection pressure runs toward the obvious by construction.** No re-weighting helps: there is
no term in the composite that can reward a thing the evidence cannot yet confirm.

### 9.3 The buyer-facing half — measured 2026-08-21

Full report: scratchpad `RESEARCH_D_buyer_facing_measured_2026-08-21.md`. Five findings with
numbers, each with a locator and a kill condition.

| # | Finding | Measured | Locator | Cost to fix |
|---|---|---|---|---|
| B1 | Packs repeat each other | median **23.7%** of a pack's sentences appear in >=50% of the catalogue (n=150 bundles); `"Fifteen minutes this week or next?"` byte-identical in **136 of 161** | `pack_linter.py:198 check_repetition` sees one pack at a time; `config.yaml:1919 lint_repetition_block: false` | $0.00/pack |
| B2 | Search returns nothing for plain English | **14 of 27** buyer queries return zero against 77 live packs (`side hustle` 0, `cleaning` 0, `dentist` 0); plurals break six pairs (`vet` 1, `vets` 0) | `Store.Web/src/lib/discovery.ts:246 matchesQuery` is a raw substring match | stemming $0.00; alias field <1% of a PASS |
| B3 | Related-packs ties | scorer emits **10 distinct values**; **32 of 77** packs have more than 3 candidates tied for 3 slots | `discovery.ts:686 scoreSimilar` | <$0.10 one-off |
| B4 | Price tracks nothing visible | **Spearman(price, sourceCount) = 0.1366**, 23 of 76 adjacent pairs inverted; the £29.99 rung carries more sources on average than £49.99 | `pricing.py` docstring claims a non-decreasing step function; `config.yaml:2102-2106` applies it at listing time only | $0.00 |
| B5 | No A/B test is possible | `resolveVariant` pins every visitor to `'a'`; counters exist and are allowlisted; last analytics read was 24 rows, all `page_view`, all dev traffic | `Store.Web/src/lib/getCopyVariant.ts` | $0.00 |

B5 is the precondition. Nothing learned on this list can be decided until randomised assignment
exists, and its own kill condition is honest: if 30 days cannot produce 126 catalogue views, no
A/B test is fittable on this site and every click-dependent proposal closes.

### 9.3b The named case the opening document could not write — shipped 2026-08-21

`pack_floors.exec_summary_md` states its own ceiling in its docstring, and both halves of it
are true:

> The WSJ formula wants a person: one named case, then the widening. This renderer cannot
> write one. It makes no model call [...] An invented protagonist would be the single worst
> thing this pack could contain.

Both true, and together they were read as "no named case is possible". That inference is
false. The dossier already holds real named cases: the passages retrieval fetched and a
`supported` check cited. Quoting one verbatim, with its URL under it, is not an invented
protagonist — it is the same standard of proof the rest of this repo already enforces.

`prospector/pack_lede.py` selects one. It makes no model call, invents no text, and prints
the source URL rather than a link with anchor text we chose.

**Measured over the 108 `*.pass.json` dossiers in the live store, and the first two numbers
are the interesting ones — both were the module grading a proxy, caught by reading its own
output rather than by a test:**

| Filter set | Yield | What the output actually contained |
|---|---|---|
| Named actor + a number | 89 of 108 (**82.4%**) | `"Temperature Log Book 6 Month Food Hygiene."` — a product listing. "Month Food Hygiene" is capitalised and "6" is a number. |
| + finite verb, + a 40% cap on capitalised words | 40 of 108 (**37.0%**) | A scraped shipping table (`"EVER MACH Oakland / Elevated / ERD drift expectation +1 to +7 days..."`), which arrives as ONE sentence because its cells carry no full stop; and French metal-detecting law (`"penalties run to €1,500 for unauthorized detection"`) opening an **AI training-data provenance** pack — cited by a check about penalties that was correctly ruled `supported`. |
| + no blank line inside a sentence, + >= 2 content words shared with the candidate | 19 of 108 (**17.6%**) | What ships. |

The third row is the contract every floor in this pack already keeps: **89 of 108 packs get
nothing here.** An absent specific is an absent line, never a padded generic one.

Three of the 19, verbatim, each with its live URL in the pack:

- *"For projects certified by DECD on or after January 1, 2021, that exceed $2.5 million in
  credit, the production company must apply and receive an audit"* — Georgia film compliance.
- *"The letter will typically say that HMRC has identified your 'adjusted net income' (ANI)
  for the tax year 2024-25 and/or 2025-26 as £60,000 or more..."* — HMRC child benefit.
- *"Manufacturing is the UK's largest claimant sector by value, with an average claim of
  £72,000 (HMRC, 2024), and the 20% above-the-line credit rises to 27% under ERIS..."* — R&D
  tax credits.

**The class this closes, and it is the one on the goal-guard list: a proxy grades nothing.**
"Has a capitalised token and a digit" is a proxy for "names somebody who did something with a
stake attached", and at 82.4% it was matching page furniture. Neither correction came from a
failing test. Both came from printing the actual output and reading it. Every filter is now
pinned by a test in `tests/unit/test_the_pack_opens_with_a_cited_case.py`, and the two
sentences above are the fixtures — the real strings, not invented ones.

**And the third instance of the same class was in the TESTS, caught by mutation.** The first
version of `tests/unit/test_the_pack_opens_with_a_cited_case.py` had one rejection fixture per
filter, all 17 green. Eleven deliberate bugs planted in `pack_lede.py` — accept any verdict,
treat scraped blocks as prose, drop the topic filter, drop the verb, drop the stake, make the
ranking arbitrary — and **6 of the 11 SURVIVED**. Each fixture was being rejected by two or
three filters at once, so the filter under test never ran. The money-outranks-percentage test
was the clearest: its percentage and duration sentences shared only one content word with the
topic, so both were filtered out before ranking and the test was asserting on a list of one.

The fix is structural, and it is the rule for any future filter added here: **every negative
fixture is ONE property removed from a single `BASE` that is asserted to pass in the same
test.** A variant can then only be failing on the property that was changed. Re-run 2026-08-21 against the rewritten tests, with a MAX_CHARS mutant added to the original eleven: **12 of 12 caught, 0 survivors.**

**Follow-through:** SHIPPED — `prospector/pack_lede.py`, wired at `pack_floors.exec_summary_md`
and `bridge.py`.

### 9.4 The constraint any fix must respect

CLAUDE.md, "two loops never merge": demand never overrides truth. An engagement score may **rank**
survivors and may **steer** generation. It must **never** un-kill an idea that failed a grounding
gate. An engagement axis wired into `kill_filter` would be the exact failure that rule exists to
prevent.

### 9.5 Where the dossiers live — wish 25

| store | verdict dossiers | catalogue rows |
|---|---:|---:|
| `~/Documents/code/prospector/store` (canonical; every plist points here) | 0 | 0 |
| 17 other laptop worktree stores | 0 | 0 |
| iCloud `prospector-ship-wt/store` | **2,044** | **0** |
| Fly volume `prospector_store` -> `/data/store` (`deploy/engine/fly.toml:65-67`) | live | unread from here |

Two defects fall out of that table. The product corpus sits in an iCloud-synced worktree that has
lost its git, not in the canonical store and not on Fly. And that store holds 2,044 dossier files
against **0 index rows**, while `store.py::save` writes the JSON and upserts the row in the same
call — so the rows were lost, not never written. `store.py:414 catalogue_titles()` and
`recent_titles()` both read that index and both are generation's cross-run dedup memory: where the
index is empty, the engine can regenerate ideas it has already ruled on and not know.

`prospector/ops/data.py::_corpus` now reports this on the ops panel: store path, whether
`PROSPECTOR_STORE_DIR` declared it, whether it is the production path, catalogue rows by decision,
and on-disk dossier files with lint receipts excluded by suffix. A read that fails is reported as
`unknown` with the sqlite error, never as zero.

### 9.6 The mechanism — three feedback loops, all carrying the same signal

The form collapse is not only a filter effect. **Generation is drifting toward the frame on its
own, and it is accelerating.** Measured on KILL dossiers only, which is generation's raw output
before the filter picks anything (96.7% of the corpus is killed):

| month | n | `<X> for <buyer>` |
|---|---:|---:|
| 2026-06 | 724 | 8.6% |
| 2026-07 | 220 | 16.4% |
| 2026-08 | 1,032 | **25.9%** |

A 3.0x rise in two months, on large samples. Including PASSes the same trend reads 8.6% → 22.0%
→ 29.4%. Within August the weekly figures are noisy (40.5% / 22.1% / 40.0% for weeks 31–33) and
should not be read as a within-month trend; the monthly series is the claim.

**Why generation drifts.** There are three paths from the filter back into generation, and every
one of them carries viability information only:

1. `prospector/adaptive.py:118 select_lenses` picks convergent or divergent lenses from
   `exploration_level`, which is derived from the **kill rate**.
2. `prospector/adaptive.py::get_recent_failure_modes` mines recent kill reasons, incumbents and
   refuting sources and feeds them into the generate prompt. Its own docstring calls this "the
   learning signal".
3. `prospector/critique.py::_axes_brief` renders the composite axes from `cfg.weights`, heaviest
   first, and `critique_revise` asks the model to rewrite each idea to remove its weakest axis.

So the loop closes: the composite prefers one shape, the survivors are that shape, the feedback
tells generation which shapes died, and generation converges. Nothing in any of the three paths
can carry a signal about whether a person finds the idea interesting, because nothing measures it.

**This changes the reading of two switches that are deliberately OFF.**

`generation.critique_revise.enabled: false` (`config.yaml:1498`) is recorded as off for cost —
one extra generation call per wave. That is not the important reason. `critique_revise` is a
gradient step on the composite: it moves every idea toward the shape the composite already
rewards. Turning it on would raise composite scores and accelerate the collapse, and the
before/after would look like an improvement on every metric the engine currently has. **Do not
enable it until an engagement metric exists to measure what it costs.**

`lane_quota_mode: measured` (`config.yaml:1519`) is off with a reason already close to correct —
"an unreserved value-weighting would starve [venture] into never producing the evidence that
would revive it". The same argument applies to critique_revise and was not made there.

**Caveat, stated rather than buried.** `select_lenses` landed 2026-08-19 and this corpus ends
2026-08-15, so **none of the data above tests the lens rotation**. The drift measured here is the
behaviour it was written to fix, not evidence that it failed. Re-run the monthly series against a
corpus that extends past 2026-08-19 before crediting or blaming it:
`scratchpad/measure_template.py` and the by-month block in this section.

### 9.8 The downstream synthesis question — measured, and on the list

Founder directive 2026-08-21: the engine generates ideas and nothing acts on the data it produces;
the kill log should be mined for missed opportunities and synthesised into better ideas, *"a slower
process but ca end up yield better output"*.

The measurement is in **[docs/RESEARCH_INDEX.md section 10](RESEARCH_INDEX.md#10-the-downstream-synthesis-programme--mining-the-kill-log)**
and it is not being built. Three numbers decide the design, so read them before proposing anything:
the kill log holds **46,220 cited sources across 17,687 hosts**; **48.1% of kills are retrieval
failures rather than idea failures** (67.6% in August); and `prospector/denylist.py` already owns
kill-corpus mining while reading **18.8%** of the log and none of the sources.

### 9.7 Where an engagement signal would attach

The three paths in 9.6 are the attachment points, and they are the only ones. A fourth loop is not
needed and would be a second implementation of one class. In priority order:

1. **A rubric that scores one candidate for engagement**, independent of evidence volume — this is
   the missing instrument and everything else waits on it. It must not read the retrieval count,
   or it re-measures viability under a new name.
2. **Rank only, at first.** Feed it into `score.py` as a reported column that orders survivors and
   changes no gate. That is measurable against the baseline in 9.0 with no risk to the money path.
3. **Steer second**, through `select_lenses` and the generate prompt, once the rubric has a
   baseline and a null.
4. **Never into `kill_filter`.** Section 9.4.

---

## 10. The specialist code review, 2026-08-21

Founder directive, verbatim: *"etrene code review by top nathenatician and nachine learning
specialist - both need to do extentive resach be fore reviewwing and doubel thriple cgeck their
nuers ad counent rigirously"*.

Two reviewers ran in parallel over the engine, read-only, with no model spend. What follows is
their output after I re-verified on disk every claim that changed code. Where my own measurement
disagreed with theirs, my number is the one printed and the disagreement is stated.

### 10.1 The bar these reviews were held to, and why it is not a persona

A persona label buys no accuracy. The measured result is that 162 role labels across 2,410
questions produced no gain, and adding identities cut one task from 68.1% to 29.3%. So "top
mathematician" and "ML specialist" are not what made these reviews good. Three mechanical
conditions did, and they are the standing bar for any review of this engine:

1. **Research before reviewing.** Grade against a published standard, not intuition. The ML
   reviewer read arXiv:2407.09007 in full before judging `denylist.py`, which is the only reason
   finding 10.5 exists.
2. **Two angles that can fail differently.** Every number carries the command that produced it and
   a second route that agrees. A static grep and an executed repro are two angles; two greps are one.
3. **An executed repro, not a reading.** A claim about what code does is a hypothesis until it has
   been run.

Both reviewers were also required to report what is CORRECT, to attempt to refute their own
findings, and to mark each one CONFIRMED or HYPOTHESIS. Two findings were withdrawn by their own
authors under that rule, which is the rule working.

### 10.2 The class: a component's own failure written as a finding about the idea

This is one defect wearing three costumes, and the engine has already paid for it once. The
dossier `store/dossiers/2102bacc6dd75cf9.kill.json` is a KILL on `min_composite` whose seven
checks all read "Verdict call failed; fail-safe" — a candidate killed by our own outage, in a
document that reads as fully reasoned. `verify.run_check` was fixed then, and its error path is
now the reference pattern: `degraded=True, retrieval_failed=True`, which fires DEFER.

The review found the same class alive at the two stages *after* it, escaping in opposite
directions.

| # | Where | What a failure was written as | Reaches |
|---|---|---|---|
| 10.2a | `prospector/verify.py` `adversarial()` | "no decisive case against it" | PASS, and **publishes** |
| 10.2b | `prospector/score.py` `score_candidate()` | "composite 0.0, below the bar of 2.5" | a false, buyer-facing KILL |

**10.2a — CONFIRMED, fixed.** `adversarial()`'s catch-all returned
`AdversarialResult(kill_case="adversarial call failed", decisive=False)`. `AdversarialResult` had
no failure field, and the consumer reads `adv.decisive` only, so the candidate reached
`Decision.PASS` with `provisional=False` and satisfied the publish condition. The sentinel string
occurred exactly once in the repo: written, never read. Aggravating: `@track_latency` logs
`status=success` whenever the wrapped call returns, so a systematically failing adversarial stage
was invisible in telemetry.

**10.2b — CONFIRMED, fixed.** `ScoreResult.score_failed` exists and carries the comment "Lets the
publish gate distinguish 'scored and weak' from 'could not score'". It had zero readers in the
package: `grep -c score_failed prospector/dossier.py` returned `0`. A scoring outage on a
candidate whose six checks were all grounded and supported wrote a KILL quoting a bar the idea was
never measured against.

Both now route to DEFER through the existing mechanism, with reasons that say what actually
happened and refuse to imply a verdict. The guard is
`tests/unit/test_a_failure_is_never_a_finding.py`, which carries a **control arm** — the same
pipeline with nothing broken must not defer — so it cannot pass on an engine that defers
everything. All three fixes were mutation-proved: each one reverted, the corresponding test fails.

### 10.3 One source cited three times scored as three sources — CONFIRMED, fixed

`verify._calc_confidence` filtered citations to valid source ids but never deduplicated them, so
`fraction = cited / total` was not a fraction and `saturating = min(1, cited / 3)` counted one
passage repeatedly. Measured here, on one source and one passage:

| citations list | confidence |
|---|---|
| `["s1"]` | 0.63 |
| `["s1","s1"]` | 0.93 |
| `["s1","s1","s1"]` | **1.00** |
| `["s1"] * 10` | 1.00 |

One real source cited twice (0.63) scored 86% of two genuinely distinct sources (0.73). The
internal citation term reached 3.0 against its documented 0.30 cap, hidden only by the final
`min(1.0, ...)`. `prompts/verdict.md` says "cite the source_ids you relied on" and does not forbid
repeats, so this is reachable on any well-behaved reply.

This is the single highest-leverage fix in the review by ratio of impact to diff, because
`confidence` is upstream of `confidence_floor`, `min_supported_confidence`, the kill gates, and
the KILL branch of `dense_reward`. Deduplicating is one line. It is applied in two places on
purpose: in `run_check`'s citation filter, so the stored dossier is clean, and inside
`_calc_confidence`, so the arithmetic is correct read on its own and every future caller inherits
the guarantee.

**Disagreement, recorded.** The mathematician reported 0.45 at one citation where I measure 0.63.
The gap is the relevance term, which depends on the passage — the mechanism reproduces exactly and
the absolute value does not transfer between passages. Any number quoted from this table must name
its passage.

### 10.4 A deliberate non-fix: `FAMILY_GATES` — CONFIRMED, NOT fixed, and this is the decision

`prospector/denylist.py:33` declares `FAMILY_GATES = frozenset({"value_durability", "incumbency",
"adversarial"})`. The only literal the adversarial path ever emits is `"adversarial_decisive"`
(`prospector/verify.py:1262`, `prospector/kill_filter.py:62`, `prospector/dossier.py:160`), so one
third of the declared set matches nothing. It is a one-character-class fix and I did not make it.

Correcting the string would *enlarge* the denial list, and finding 10.5 says the denial list is
the part of the engine standing on the weakest ground. Making a mechanism bigger while its
justification is in question is the wrong order. This is a founder decision, not a typo.

### 10.5 The denial list cites a paper that describes a different mechanism — CONFIRMED

`prospector/denylist.py` cites "DENIAL PROMPTING (arXiv:2407.09007)". The ML reviewer read it:
*Benchmarking Language Model Creativity: A Case Study on Code Generation* (Lu et al., 2024).
Denial prompting there is per-problem and single-thread — the model detects a technique inside its
own just-generated solution, and that technique constrains the next turn, on the same problem, up
to T=5. The paper makes no cross-problem transfer claim.

`denylist.py` inverts all four properties: it mines an **external** corpus of KILLed candidates
into a **standing** list, injected into **fresh, unrelated** generation prompts, persisted across
runs. The shipped directive asserts the transferability the paper does not claim, verbatim: *"they
are DEAD regardless of sector or wording"*.

The paper's own numbers argue against the implementation. GPT-4, constraint states 0 → 5:

| state | pass@1 | convergent | divergent | constraint-following |
|---|---|---|---|---|
| 0 | 16.1% | 16.2% | 4.5% | 100% |
| 1 | 11.6% | 8.1% | 11.9% | — |
| 5 | 2.1% | 0% | 15.3% | 14.4% |

Novelty rises, correctness collapses. `max_families: 12` carries up to 12 simultaneous
prohibitions, well past the T=5 at which the cited paper measured constraint-following at 14.4%
and convergent creativity at zero — and in this pipeline, generation feeds a paid verification
moat, so correctness traded for novelty is money spent on candidates that then fail the gates.

The citation should be removed or corrected regardless of what happens to the mechanism: it
currently reads as published support for something the paper neither describes nor tested.

**Second, independent defect in the same file — CONFIRMED.** The PASS exclusion compares each PASS
row to the family *seed* only, never to the family's other members, and clustering is greedy and
seed-anchored. A constructed family survives exclusion with a PASS row at Jaccard 0.800 from
member 3 while sitting 0.333 from the seed — so a proven-good idea is injected into the generation
prompt as DEAD. Jaccard supports a metric, but membership judged against a single anchor gives no
bound on member-to-member distance, so seed-proximity does not transfer.

### 10.6 Two numbers the engine is not entitled to claim — CONFIRMED

**The golden gate cannot support a discrimination claim.** `fixtures/golden_set.json` is n=9, 7
KILL / 2 PASS. Stamping KILL on everything scores 0.7778, and a constant-KILL stamper produces a
flawless 9/9 about once in ten runs — `(7/9)**9 = 0.1042`. A perfect 9/9 has an exact 95% lower
bound of 0.6637, *below* the majority baseline. Both reviewers computed this independently and by
two routes each (bisection on the binomial tail and the closed form), agreeing to 1e-6. The
promotion gate's three runs reuse the same nine items, so they are repeat measurements of one item
set, not independent trials.

Two further facts from the fixture file itself: both PASS cases — the only two items carrying
discriminative power — say in `label_basis` that they were rewritten on 2026-08-15 because both
brains killed them; and one of the nine says of itself that *"NO FIXTURE ENTRY EXISTS for this
idea"*. The fixture last changed at 2026-08-15 10:01, and the `moat_primary` promotion landed at
13:01 the same day.

This does not retroactively invalidate the MiniMax promotion, and it is not an argument to revert
it. It means the golden gate must be described as what it is — a smoke test that the lane runs
end to end — until it is grown past the majority baseline with held-out items. n=42 distinguishes
0.95 from 0.80 at 80% power.

**A market is declared READY on one decided candidate.** `prospector/markets.py` computes
`discrimination = correct / decided` with no minimum sample size. `n_candidates` is recorded and
printed and gated nowhere. A constructed market with 10 candidates, 9 deferred and 1 decided,
returns `discrimination 1.0, defer_rate 0.9, verdict ready`. Exact Clopper–Pearson on 1/1 gives a
lower bound of 0.025 against a bar of 0.70. `defer_rate` is computed, returned, and gated by
nothing. Readiness gates market entry.

**And the pooled rates can invert the ranking across the shipped bar.** `grounding_rate` and
`authority_rate` are micro-averages over candidates with very different check and source counts —
the textbook Simpson configuration. A constructed pair where market A grounds better than market B
on *every single candidate* gives A `0.5364 → not_ready` and B `0.7636 → ready`. Verified in exact
rational arithmetic outside the module, so it is not float noise.

### 10.7 Order-dependence in dedup — CONFIRMED

`difflib.SequenceMatcher.ratio()` is not symmetric, and `prospector/dedup.py:62` asserts that it
is. `find_longest_match`'s documented tie-break is not swap-invariant, so the matched-block total
changes when the arguments swap. Measured: 9.59% of 200,000 random short pairs are asymmetric
(worst gap 0.533), rising to 62.46% on realistic phrase pairs. The consequence is at the catalogue
level — `dedup([A,B])` drops one and `dedup([B,A])` keeps both, so what is in the catalogue depends
on arrival order. `max(ratio(a,b), ratio(b,a))` is the fix.

Separately, the calibration comment claims dupe pairs score ≥ 0.38 and distinct pairs ~0.00. On
the real titles in `tests/unit/test_dedup.py` the only thresholds that separate the corpus
perfectly are `(0.2222, 0.2500]`; the shipped 0.34 sits far outside it, and 3 of 7 same-idea pairs
fall below it. The pinned test passes on 12 of the 24 possible input orders. And at 0.34 the
Jaccard bound makes any pair whose token-set sizes differ by more than 2.94× invisible even under
total containment — a 27-token restatement literally containing all 4 tokens of a title scores
0.1481 and is not a duplicate. The same threshold binds `denylist.py` and `diversity.distinct_k`.

### 10.8 The instrument that would catch generation collapse is blind, and unread — CONFIRMED

`diversity.distinct_k` clusters on the same lexical Jaccard. Ten restatements of one idea in
disjoint wording score **10 of 10** — perfect diversity. Ten lexical near-copies score 1 of 10.
Denial prompting forbids lexical families, which pushes the generator to re-skin one idea in new
vocabulary: precisely the case the meter scores 10/10.

And nothing reads it. `write_receipt` has no reader, no threshold and no brake;
`kill_decay.check_diversity_floor` has zero production callers; the `diversity_collapse` alarm is
reachable only from `simulation.py`, which neither `run.py` nor `prospector/scheduler/` imports.
So the answer to "would we notice if generation collapsed" is no — three instruments exist, two
are unreachable, and the reachable one cannot see semantic collapse.

### 10.9 Lower severity, confirmed, not fixed

- **Relevance rewards padding.** `verify.py`'s relevance term is recall of question words with no
  precision term and no length normalisation, so a 4,000-word junk passage containing every
  question token scores 0.75 against an on-topic short passage's 0.57.
- **The relevance denominator varies 8× across checks.** Credit per matched token runs from 0.0375
  (`value_durability`, 8 tokens) to 0.0047 (`currency`, 64 tokens), all graded against one
  `confidence_floor`. The split is whitespace-only, so 65 of 239 question tokens (27.2%) carry
  punctuation and can only match a passage token bearing identical punctuation.
- **The composite has no provenance.** `run.py` passes the **non-critical** chain as the scorer.
  `ScoreResult` has no provider field and the store schema has no provider column — while
  `CheckResult.provider`, `AdversarialResult.provider` and `Dossier.provider_chain` all exist
  precisely so brains can be audited. `min_composite_to_pass` is an absolute bar on a number that
  cannot be attributed, so scorer drift is undetectable from disk.
- **A per-call market override is honoured for half its keys.** `prompts.market_kwargs(market=X)`
  passes X to the block but not to the fragment chain, so three exemplar keys silently follow
  `cfg.active_market`. 3,322 bytes of US-specific query exemplars exist on disk and are never
  served; the UK file is served instead. The moat is not affected — the scheduler rebuilds config
  per market — but per-candidate pack generation is. The docstring immediately above the defect
  documents this identical class being fixed for currency; the override was added to one and not
  the other.
- **Provider health has a cross-process lost-update window.** `_claim_probe` takes an `fcntl`
  lock and its docstring explains at length why a `threading.Lock` cannot do this job.
  `mark_exhausted` and `clear` do load-modify-save without it. Reproduced by the file's own
  documented method: a brain that just proved itself alive is silently re-benched for the full
  hour. The daemon and a `vet --resume` drain are separate processes on one store — the exact
  pair the docstring names.
- **A lane may override weights and skip validation.** `config.for_lane` merges weight overrides
  and never revalidates, while the market path is guarded. A lane summing to 1.65 raises the
  ceiling to 8.25 against an absolute `min_composite_to_pass`, flipping a verdict on identical
  evidence. Latent — no shipped lane declares weights — and the fix is one call.
- **The RL signal rewards an outage over a marginal pass.** `Dossier.dense_reward` scores a PASS
  with no score at all at 0.92, above a genuine PASS at the live bar at 0.90, because the
  missing-score fallback is a hardcoded composite of 3.0. Its KILL branch is mean check confidence,
  which is polarity-blind, so the signal rises with how well an idea was proved dead.
- **A malformed verdict token is scored as evidential absence.** `_coerce_verdict` maps an
  out-of-vocabulary string to `UNVERIFIABLE` with no `degraded` and no `retrieval_failed`, so it
  reaches the kill gates as a genuine finding. Low severity: `prompts/verdict.md` constrains the
  output vocabulary to exactly the enum, so this needs a model error rather than a systematic
  mismatch. It is a one-line gap in an otherwise consistent policy.
- **The prompt suite leans permissive.** The only precedent in the base `prompts/verdict.md`
  teaches SUPPORTED from thin evidence and is followed by "Do not act like a pedantic computer",
  under a SYSTEM line reading "NEVER 'supported' without a passage that directly supports it". The
  REFUTED precedent teaches good evidence using an invented statute — in an engine whose first
  rule is source-or-die. `prompts/score.md` carries the matching asymmetry.
- **FX rounding.** `round()` is banker's rounding on money: 13 of 400,000 scanned amounts disagree
  with exact `Decimal` ROUND_HALF_UP by 1 penny, and 5 disagree on operand order alone. The USD
  rung ladder is positional rather than converted, so the implied rate per rung spreads 12.00%
  against a declared 1.34980, and `usd_rungs` has 7 entries against 5 `rungs` with nothing
  validating the two lengths against each other. Bounded: `comparables.rung_adjust_enabled` is
  off, so none of it moves a price today. The ladder spread is live regardless.

### 10.10 Checked and found correct

Reporting only defects makes a review unfalsifiable. These were attacked and held.

- `config._validate_weights` enforces axis membership, non-negativity and sum-to-1.0 within 1e-6,
  fails loudly at startup, and correctly refused three deliberately-bad blocks. Live weights sum
  to exactly 1 in rational arithmetic.
- `health._claim_probe` under concurrency is correct: `fcntl.flock` on a dedicated lock file makes
  load-decide-write atomic machine-wide, with the thread lock kept as a fast path. `_save` writes
  to a temp file and `Path.replace()`s, so a reader outside the lock cannot see a partial file.
- **The trusted/provisional fence holds.** One provisional check taints the whole dossier, and
  `make_operator` stamps the tier name on the single-tier case so a bare `operator: minimax` cannot
  rule as trusted. Neither reviewer could construct a path where an untrusted brain publishes. A
  suspected thread-local trust leak in `FallbackOperator._served` was investigated and **refuted**:
  the only `ThreadPoolExecutor` in `verify.py` submits retrieval, not verdicts.
- `run_check`'s error path is the correct pattern and is the reference the two fixes above copy.
- The empty-rationale guard is exemplary — it treats a well-formed reply with a blank argument as
  a failed call, and was justified with a real measurement before shipping.
- `errors.classify_exhaustion` matches HTTP codes on word boundaries with PERMANENT winning ties.
- `prescreen` fails open by design and says so; `llm_called` keeps the cost visible.
- `pricing._band_index` is non-decreasing in source count by construction, and `_usable_bands`
  validates length against rungs with loud logging — which is exactly what `usd_rungs` lacks.
- `lane_yield`'s shrinkage is dimensionally correct and refuses to divide when the global mean is
  non-positive; the largest-remainder apportionment is the right choice and is correctly stated.
- **`round(..., 4)` in `score.composite` is correct to keep.** The composite lattice is 46,656
  vectors → 101 distinct exact values, smallest gap 0.05. At every *live* bar there are zero
  float-vs-rational disagreements with or without the round; at one comment-only bar the unrounded
  sum misclassifies 5 vectors reading `3.1999999999999997`. 1,198 vectors land exactly on the 2.5
  bar, so the knife-edge is real and is currently handled. The mathematician's first conclusion
  here was refuted by their own second angle and then re-established only for a non-live bar —
  recorded because that is the process working, not a wobble.

### 10.11 What is fixed, and what is not

Fixed in this change, each mutation-proved:

| Finding | Change |
|---|---|
| [10.2a](#102-the-class-a-components-own-failure-written-as-a-finding-about-the-idea) | `AdversarialResult.retrieval_failed`; the consumer defers on `adversarial_unrun` |
| [10.2b](#102-the-class-a-components-own-failure-written-as-a-finding-about-the-idea) | `build_dossier` reads `score.score_failed` and defers on `score_failed` |
| [10.3](#103-one-source-cited-three-times-scored-as-three-sources--confirmed-fixed) | citations deduplicated in `run_check` and in `_calc_confidence` |

Not fixed, deliberately, and each needs a decision rather than a patch:
[10.4](#104-a-deliberate-non-fix-family_gates--confirmed-not-fixed-and-this-is-the-decision) and
[10.5](#105-the-denial-list-cites-a-paper-that-describes-a-different-mechanism--confirmed) are one
question — whether the denial list stays at all;
[10.6](#106-two-numbers-the-engine-is-not-entitled-to-claim--confirmed) is a claim to stop making
until the fixture grows; [10.7](#107-order-dependence-in-dedup--confirmed) through
[10.9](#109-lower-severity-confirmed-not-fixed) are ordinary work, ranked in that order.

### 10.12 What neither reviewer could measure

Neither could state a production **incidence** for any of this. There is no verdict corpus
reachable from the engine's own store: `store/dossiers/` holds 14 lint receipts and no dossiers,
and the canonical store's dossier directory is empty. Every finding above is therefore a statement
about the function, not about the catalogue. That is a fact about where the corpus lives, which is
already a known defect and is with the platform engineer.

---

## 11. Action items, tracked — 2026-08-21

The founder's instruction: *"research findings need o be fiolloweed htru"*, *"not just fucing
wiring docs"*, *"the gol os the rearc is to inporve the systen nont to ead fuckig sunnaries"*.

Every finding in the bench notes now has a number a machine can check. A finding with no row here
is a finding that has not been followed through. **Four of these need the founder and nobody else;
they are marked FOUNDER and no agent can close them.**

### 11.1 Shipped — the system behaves differently now

| What changed | Where | Proof |
|---|---|---|
| An `unverifiable` ruling no longer carries grounding confidence | `prospector/verify.py:761` | PR #570, merged. Corpus: 9,965 `unverifiable` checks scored mean 0.5627 against 0.5695 for `supported` — a +0.0019 gap, and 73.3% of unruled checks scored >= 0.5. `_calc_confidence` has no verdict term; it measures what retrieval returned. |
| A research report must name its follow-through, and a test fails if one does not | `tests/unit/test_a_research_finding_must_name_its_follow_through.py` | PR #571, merged. 15 reports carry `**Follow-through:**` as SHIPPED / TICKET #n / NO ACTION + reason. The unknown branch calls `pytest.fail`, so a new state cannot pass silently. |
| The opening document quotes a real named case out of a cited passage, instead of having none | `prospector/pack_lede.py`, wired at `pack_floors.py` `exec_summary_md` and `bridge.py` | Section 9.3b. 19 of 108 live pass dossiers (17.6%) produce one; the other 89 print nothing rather than a generic opener. Two earlier filter sets scored 82.4% and 37.0% and were both matching page furniture. |
| The cost rule no longer contradicts the founder's own ruling in four places | this commit, A6 section + E-020 + E-103 + the axes table | Line 69 was corrected on 2026-08-20 and the other four sites were not. |

### 11.2 Open, and an agent can move them

| Finding | Number | Blocked on |
|---|---|---|
| E-001: the golden set is saturated at 1.00 on 9 items, and it gates every quality experiment | #573 | nothing — this is the one to do first |
| Six of nine axes have no baseline, so 1000x on them is undefined | #575 | nothing for A2/A3/A7; A8's second half needs #573 |
| E-023: 11,250 chars of identical preamble on every call against 1,500 of evidence | #577 | nothing |
| Soft early-exit is inert — 23.1% of every verdict call is bought after PASS is provably impossible | #578 | #579, and a LAW 11 broadcast |
| Two dossiers PASSed although `pass_impossible_reason` says PASS was impossible | #579 | nothing |
| Retrieval is the quality ceiling, not the model: 73.3% of checks abstain (E-042, E-043) | #582 | #573 |
| E15: 45.8% of ruled rationales do not entail from the passages they cite (E-102) | #564 | a live brain |
| L1: 21.84% of checks refetch a url already on disk | #566 | a founder call on the TTL |
| E5: the coverage sampler's flag has never been switched on | #567 | nothing |
| E2: one persona has never produced a dossier; 12.87x pass-rate spread unexploited | #565 | #552 |
| Packaging, pricing and defensibility — the research that never launched | #583 | nothing |
| Who buys a claim-level verdict with consequences attached | #584 | nothing |

### 11.3 FOUNDER — no agent can close these

| Decision | Number | What is actually being asked |
|---|---|---|
| A1 is 0%: the Fly engine has no trusted brain | #576 | MiniMax credit, or `claude setup-token` on the box. Money or a login. |
| E-106 Groq free tier | #580 | May candidate text and retrieved passages be posted to a free tier whose retention terms we have not accepted? The capacity half is settled: 13.4 vets/day today, 37.3 after the call merge. TPM binds, RPM never does. |
| Re-test E-101 against the graders it could not run | #581 | A one-off spend of under $1 against Google Check Grounding and Bedrock. Estimate posted before the run, per wish 14. |
| L1 retrieval cache TTL | #566 | 21.84% reuse, 19.71% under a 30-day window. Whether a cached page is still evidence after 30 days is a standard-of-proof question, not an engineering one. |

### 11.4 Closed by a measurement — do not rebuild these

| Claim | Why it is closed |
|---|---|
| "Batching query generation across the six checks is worth ~2.5x" | **False, corrected on #560.** `gen_queries_batched` is already called at `verify.py:1087` with `llm_query_gen: true` at `config.yaml:572`. And `tools/engine_baseline.py:203` increments `paid` once per CHECK, so the 4.991 counts `verdict_for` calls only — 14,006 checks / 2,806 dossiers = 4.9915. Query generation was never in that number. |
| "A BM25 near-miss passage index would pay for itself" | Measured 11.91% reuse against a 20% bar, an 8.1pp gap. Exact-key repeat on the shipped cache is 0.01%. |
| "A free verifier we own can replace the paid call" | E-101, eight arms, 3,472 pairs each. Best 0.706 AUC, worst 0.408. Stands **on the arms tested** — #581 is the honest remainder. |
| "The estate-map citation guard catches drifted citations" | It caught 1 of 3 identical +30-line drifts, because its +/-3 window let a citation inherit a neighbour's symbols. #572. |
