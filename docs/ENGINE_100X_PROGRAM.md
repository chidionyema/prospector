# The 100x Engine Programme

**Status: OPEN. Started 2026-08-20.** Branch `perf/engine-100x`, worktree
`/Users/chidionyema/Documents/code/wt-engine100x`, based on `origin/main` at `8c0c821e`.

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

### What that translates to, operationally

| Wish | Operational rule for this programme |
|---|---|
| independent of cost | Cost is NOT an optimisation target. It is a recorded observation only. No experiment is rejected for being expensive. |
| 100x, all round | Every axis in section 1 carries a 100x target. Aim for it even where it is not reachable; record the number actually reached. |
| benchmark strictly | Section 2 is the admissibility bar. A number that fails it does not go in the ledger. |
| metric for everything | No axis without a unit, a baseline, and a command that reproduces it. |
| strong proof | Every ledger row carries a receipt: a command, a commit SHA, and the raw output location. |
| exhaust all options | Section 3 is the backlog. It is closed only when every row is DONE or REJECTED-with-a-reason. |
| all experiments and outcomes | Negative results get rows. See section 4's rule. |
| state of the art | Section 5 tracks what the literature and the open-source field do that we do not. |
| any resource is available | Hosted models, paid APIs, local models, extra machines are all in scope. |

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
| A6 | Cost | USD per 1000 verdicts | ~$3.60 (MiniMax M3, 10k in / 500 out assumed) | observation only | estimated, not measured |
| A7 | Grounding fidelity | % of verdict citations whose anchor text literally appears in the fetched passage | TBD | 100% | NOT MEASURED |
| A8 | Abstention calibration | accuracy on attempted, vs % attempted | TBD | see E-045 | NOT MEASURED |

### A4 is the blocker, and it is the first finding of this programme

Discrimination is **1.00 on a 9-item golden set**. That is not a good score. It is an unusable
instrument. A benchmark that is already saturated cannot register any improvement, and cannot
register a regression either. Every quality claim this programme makes would be unfalsifiable
against it.

So experiment **E-001 blocks every quality experiment**: build a golden set with resolution.

### A6 is deliberately not a target

The founder's words are *"indepenent of cost"*. Cost is recorded so that a 100x latency win bought
with a 1000x cost increase is visible as what it is, and so the founder can make the business call.
It is never a reason to reject an experiment inside this programme.

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
| E-020 | The six checks run SEQUENTIALLY under kill-fast. Kill-fast is a COST optimisation, and cost is no longer a constraint. Running all six concurrently and cancelling on the first hard fail should cut p50 by close to 6x on candidates that survive, at the price of wasted calls on candidates that die early. |
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

### Group 4 — quality (A4, A7, A8) — all blocked on E-001

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
| — | — | No experiments run yet. Programme opened 2026-08-20. | — | — |

---

## 5. State of the art — what the field does that we do not

Researched 2026-08-20. Full reasoning in the session transcript; the load-bearing conclusions:

- **The moat's verdict step is the academic fact-verification task.** FEVER's
  `SUPPORTS / REFUTES / NOT ENOUGH INFO` maps one-to-one onto `supported / refuted / unverifiable`.
  We are treating a classification problem as a generation problem.
- **Purpose-built models beat frontier models at it, at a fraction of the size.**
  Bespoke-MiniCheck-7B tops the LLM-AggreFact leaderboard at 77.4%, above Claude 3.5 Sonnet.
  HHEM-2.1-Open scores 71.8% in under 600MB of RAM and about 1.5s per 2k tokens on an x86 CPU.
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
| **E-103** | Concurrency across the six checks WITHIN one candidate, with kill-fast retained as a cancel rather than a gate. E3 measured concurrency across candidates; this is a different axis and it is the direct p50 win. | Cost is explicitly not a constraint, and kill-fast is a cost optimisation. | READY |
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
