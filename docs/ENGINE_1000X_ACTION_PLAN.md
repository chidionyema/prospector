# The 1000x Action Plan

**Status: OPEN. Written 2026-08-20.** This is the WORK LIST. `ENGINE_100X_PROGRAM.md` is the
RECORD — axes, baselines, and the ledger of what was run. Nothing goes in the ledger until it has
a receipt; everything here is a thing to do until it does.

## The goal, in the founder's words

> *"1000x is the headline of the project"* · *"we want 1000 inprovebtbts all ways"*
> *"when i said 100, i nean all ways ... every ook and cranny pf engine"*
> *"we aloed n=to nke the engine as cheap as possible t ru while beig 1000 bettr also"*
> *"we need to neasure everything, baseline ad get t work"*
> *"we need to be cretive, think out of the bo and reserach"* · *"and we need proof"*
> *"we need to win close the shpe and actully delober"*

Two targets at once, and they pull against each other on purpose: **1000x better on every axis,
and as cheap as possible to run.** Cost is no longer an observation. It is an axis with a target,
the same as the rest.

## The rule every row on this list obeys

| Field | Meaning |
|---|---|
| **Axis** | which axis in `ENGINE_100X_PROGRAM.md` §1 it moves. A row that moves no axis is not work. |
| **Cost class** | ONE-OFF (an experiment, a rented box that gets destroyed) or OPERATIONAL (bills forever, grows with volume). An operational cost needs a creative answer, not a purchase. |
| **Estimate** | written down BEFORE the thing runs, never after. |
| **Proof** | the command, and the SECOND independent angle. One measurement is a reading; two that agree are a proof. |
| **Blocker** | what it waits on. "Nobody" means start it now. |

---

# Phase 0 — the fire. A1 is 0% and nothing else can be measured on a dead engine.

The engine on Fly logs `moat_blind` every tick and retries in 300s. It cannot mint a verdict at
all, so every quality number in this plan is currently unmeasurable on the machine that matters.

## 0.1 Get the Claude CLI ruling on `prospector-engine` — FOUNDER, one command

**The mechanism exists and it is not a credential copy.** `claude setup-token` (Claude Code 2.1.237,
`claude setup-token --help`) mints a **long-lived authentication token** against a Claude
subscription. That is a purpose-made headless token, not the founder's interactive session
credentials — which are an OAuth access/refresh pair in `~/.claude/.credentials.json` and must not
leave this laptop.

```
claude setup-token                                  # founder runs this; it prints a token
fly secrets set CLAUDE_CODE_OAUTH_TOKEN=<token> -a prospector-engine --stage
```

Staged rather than set, so no machine restarts and the token arrives with the next deploy.

- **Axis:** A1, 0% → serving. **Cost class:** none — the subscription is already paid.
- **Proof:** the tick log stops printing `moat_blind`; and, independently, `diagnose --deep`
  returns a discrimination number from the box rather than an exhaustion error.
- **Blocker:** the founder. This is his identity and only he can mint it.

## 0.2 The brain is already pinned to the cheapest Claude — verified, no work needed

`prospector/claude_cli.py:48` sets `CHEAPEST_CLAUDE_MODEL = "claude-haiku-4-5-20251001"`, and
`operator.py:1944-1948` passes it explicitly on every construction, falling through
`component_pin` → `cfg.claude_cli_model` → the cheapest constant. `config.yaml:219`
`claude_cli_model` is blank, which is the DEFAULT-TO-CHEAPEST path, not an unpinned one.
`tests/test_claude_cli_model_pin.py` fails if either construction site drops the pin.

Measured on this laptop 2026-08-20: `claude -p --model claude-haiku-4-5-20251001` returns rc=0 in
**21.5 seconds**. Never leave the CLI unpinned — it then uses the machine's own default, measured
as `opus[1m]` on 2026-08-19.

- **Free win found while measuring it:** the CLI prints
  `Warning: no stdin data received in 3s, proceeding without it` and waits the full 3 seconds.
  Feeding it `< /dev/null` removes 3s from **every** CLI call. At 4.679 calls per vet that is
  ~14 seconds per candidate for a one-line change. **Axis A3. Cost class: none.**

## 0.3 MiniMax credits — FOUNDER, money

`config.yaml:58` and `:81` both list `[minimax, claude_cli]`, so MiniMax leads and rules finally.
With no credit the whole head of the chain is a guaranteed failure paid before every call.
This is money leaving the account and is the founder's alone.

---

# Phase 1 — the instruments. "Measure everything" is a build, not a promise.

Five of nine axes have no baseline at all. An axis with no unit cannot be improved by 1000x,
because nobody can say what 1000x of it is. Phase 1 is the whole of "measure everything".

## 1.1 `tools/engine_baseline.py` — one command, every axis, a dated report

One command that reads A1 through A8 and writes a timestamped report. Every axis returns either a
number with its provenance or the literal string `UNOBTAINABLE` with the reason. **A missing
number is a finding, not a blank.** Runs on a schedule so progress is a series, not an anecdote.

- **Axis:** all of them. **Cost class:** none. **Blocker:** nobody. **Start now.**
- **Proof:** run it twice on an unchanged tree and diff — the numbers that should be stable are
  stable. Second angle: each axis's number is independently reproducible by the command the
  report prints beside it.

## 1.2 THE KEYSTONE — a human-labelled ground-truth set

This is the single highest-value item on the whole list and it needs no money and nobody's
permission but the founder's time. **Three separate dead ends all open from one file.**

1. **A4 is saturated at 1.00 on nine items.** A benchmark that cannot register a regression is a
   dead instrument, and it blocks E-040 through E-045 outright.
2. **E15's 48.9% rationale-infidelity rate is calibrated against a synthetic control, not people.**
   Its own writeup says so: *"tau is calibrated on the NULL control, not on human labels. No human
   has labelled any pair here, so the absolute rate is only as good as that calibration."* Two runs
   forty minutes apart gave 43.4% and 48.9%. We do not know the number to better than ±5pp.
3. **E-101 could not trust its own primary angle** because agreement-with-our-own-rulings is
   contaminated by exactly that infidelity. It needed a constructed control to say anything at all.

One human-labelled set fixes all three. Target **200 claim/passage pairs**, sampled the same way
E15 samples (systematic within verdict class, deterministic, no RNG), labelled
supported / refuted / unverifiable, stored as tracked JSONL with the labeller and the timestamp.

- **Axis:** A4 primarily; A7 and A8 become measurable for the first time.
- **Cost class:** none in money. Roughly 2–4 seconds a pair once the tool is good, so 200 pairs is
  well under an hour of founder time, and it can be done in sittings.
- **Proof:** label 20 pairs twice, a day apart, and report the self-agreement rate. A ground truth
  whose own author disagrees with himself 30% of the time is not ground truth, and we would rather
  find that out on 20 pairs than after 200.
- **Blocker:** the tool has to exist first. That is ours. Then founder time.

## 1.3 Cost meter, not cost estimate

A6 is "~$3.60 per 1000 verdicts" and that is an estimate. Every model call should write its token
counts and its tier to the ledger, so cost per verdict is a **read**, not a calculation. Without
this, no cost experiment in Phase 2 can prove it worked.

- **Axis:** A6. **Cost class:** none. **Blocker:** nobody.

## 1.4 Latency and throughput timers

A2, A3a and A3b have never been measured. Wall-clock per stage, per candidate: query generation,
fetch, verdict, adversarial, render. Recorded per run, so the p50 and p95 are a query rather than
a stopwatch exercise.

- **Axis:** A2, A3. **Cost class:** none. **Blocker:** nobody.

---

# Phase 2 — cost. Make it as cheap as possible to run.

Measured 2026-08-20 on 14,006 checks: **~11,250 characters of identical prompt preamble on every
call against ~1,500 characters of actual evidence.** The evidence is 12% of what we pay for. That
single fact is the whole of Phase 2.

| # | Item | Effect | Cost class | Blocker |
|---|---|---|---|---|
| 2.1 | **Merge the six check calls into one** — founder-approved | 2.8x tokens, 4.679x calls | none | a brain to ship |
| 2.2 | **Provider prompt caching (E-023)** on the fixed preamble | attacks the same 88% | none | none |
| 2.3 | **Passage store keyed by URL** — 21.84% of checks refetch a page we already hold | fewer fetches, faster | none | none |
| 2.4 | **Batch endpoints (E-024)** where the work is not latency-critical | provider-published discount | none | needs a metered tier |
| 2.5 | **Cascade (E-050)** — cheap model rules the easy 73%, escalate only the hard tail | unknown until 1.2 exists | none | **1.2** |
| 2.6 | **Prompt compression** on the preamble itself | unmeasured | none | none |
| 2.7 | **Drop dead weight from the preamble** — measure which of the 11,250 chars changes a verdict | direct | none | **1.2** |

2.7 deserves its own line because it is the cheapest experiment on this page and nobody has run
it: ablate each block of the verdict prompt (style 1,247 chars, market exemplars 885 chars, and the
4,220-char median candidate JSON) and measure whether the verdict changes. Any block that does not
change a verdict is pure cost. This needs the labelled set from 1.2 to grade against.

## 2.8 The constraints on the approved merge, recorded before it is built

1. **Parse the merged reply per check.** One bad parse must not defer a whole candidate onto a
   drain that is already stuck.
2. **Kill-fast must still short-circuit.** Merging removes the ability to stop after check 2. At
   4.7% `refuted` the loss is small, but it is a loss and it must be measured, not assumed away.
3. **Ship behind the mock gate first** (`tests/test_golden_set.py:163`, `MockOperator` at `:171`,
   no brain required), and land only after the live nine-item run clears.
4. **The long tail must fit the context.** Candidate JSON has a median of 4,220 chars and a mean of
   19,756 — the mean is 4.7x the median, so the tail is real.
5. **Provider-agnostic.** The merge must not assume one provider's JSON behaviour, or it becomes a
   reason the roster cannot widen.

---

# Phase 3 — quality. The ceiling is retrieval, not the model.

**73.3% of all 14,006 checks return `unverifiable`.** Only 4.7% return `refuted`. The engine is not
being wrong; it is failing to find evidence. Every hour spent on a better verdict model is aimed at
22% of the traffic.

| # | Item | Axis | Blocker |
|---|---|---|---|
| 3.1 | Query expansion without a model — RM3 pseudo-relevance feedback, doc2query at index time | A7, A5 | 1.2 |
| 3.2 | Cross-encoder reranker on retrieved passages (E-043) | A7 | 1.2 |
| 3.3 | Structured sources that beat general web search for business claims — registries, filings, statistical offices, pricing pages | A7, A5 | research |
| 3.4 | Separate "no evidence exists" from "we searched badly" — abstention calibration (A8) | A8 | 1.2 |
| 3.5 | Re-measure rationale infidelity against HUMAN labels (E-102) | A7 | 1.2 |
| 3.6 | Generalise the literal-anchor rule from price comparables to every check | A7 | none |

3.6 is the one that needs no research and no labels. `price_comparables` already enforces that
every anchor must appear **literally** in the passage it cites. That rule is the reason the price
check cannot hallucinate. Nothing stops us applying the same rule to every check's citations, and
it would put a hard floor under A7 by construction rather than by measurement.

---

# Phase 4 — every nook and cranny, including the content

The founder's words: *"every ook and cranny pf engine, needs epltih, the content generaton"*.
The verdict path has had all the attention. These have had none.

| # | Area | What has never been measured |
|---|---|---|
| 4.1 | **Content generation** — the £49 deliverable the buyer actually reads | no quality metric of any kind. `PACK_NARRATIVE_PROGRAM.md` names eight deterministic renderers and three gates that grade less than they appear to. |
| 4.2 | **Candidate generation** | how many generated candidates are near-duplicates of the catalogue, and how much of the divergence is real |
| 4.3 | **Prescreen** | its false-negative rate. A prescreen that kills a good candidate is invisible by construction — nothing downstream ever sees it. |
| 4.4 | **Scoring** | the six axes and their weights have never been validated against an outcome |
| 4.5 | **Pricing** | the rung ladder has never been tested against what anyone actually paid |
| 4.6 | **Dedup** | `difflib.SequenceMatcher` + Jaccard, not embeddings. Never measured against a labelled duplicate set. |
| 4.7 | **The adversarial pass** | runs on PASS only. Its catch rate is unknown. |

4.3 is the quiet one. A prescreen false negative destroys value silently and permanently, and
because the candidate never reaches a dossier there is no record it existed. Measuring it means
running the full pipeline on a sample the prescreen killed, which costs verdicts — so it is a real
experiment with a real cost estimate, not a free scan.

---

# Phase 5 — the cadence. Regular reports, or none of this is provable.

Founder: *"we need to save all report an progres regunalrt, regu;ar updtes"* and
*"dont hold all this i nenory"*.

1. `tools/engine_baseline.py` writes a dated report every run. Reports are tracked, so the series
   survives a session ending, a compaction, and a machine dying.
2. Every experiment appends a ledger row to `ENGINE_100X_PROGRAM.md` §4 with a receipt, whether it
   worked or not. A negative result costs the same to produce as a positive one and saves the next
   session from repeating it.
3. This file is the work list and is edited in place as items land.

---

# Open research — commissioned 2026-08-20, results land in the ledger

1. **Every way to cut LLM verification cost 10x–100x in 2026** — caching discounts and TTLs, batch
   endpoints, cascades and routing with measured escalation rates, distillation economics,
   open-weight verifiers with real $/1M prices, prompt compression, and the subscription-CLI route
   where inference is a flat monthly fee rather than metered.
2. **How the field fixes low evidence recall** — query expansion, 2026 search API prices per 1000
   queries, whether a benchmark exists that separates retrieval recall from verdict accuracy,
   structured non-web sources for business claims, cheap CPU rerankers, and how to tell an honest
   "no evidence exists" from a bad search.
3. **Content-generation quality** — how anyone grades a generated business document, and what a
   deterministic renderer can be held to. NOT YET COMMISSIONED.
4. **Packaging, pricing and defensibility for a one-operator research product** — the question
   E-104 turned into the important one. NOT YET COMMISSIONED; it hit the agent fleet cap.

---

# Known defects, carried here so they are not lost

- **Five zero-byte dossiers on `prospector-engine`** at `/data/store/dossiers/`, all written inside
  one ~2.4-hour window 1.3–1.4 days ago, 5 of 3,622 = 0.14%. All five have a LIVE catalogue index
  row pointing at them, so the index claims a dossier that has no content;
  `scripts/restore_drill.py` already flags three under `index_vs_tree`. Reported by the DR session,
  two angles agreeing (the R2 backup objects are 0 bytes AND the local files are 0 bytes, so this
  did not happen in transit). **The file being empty is not the same as the write failing** — a
  truncate-on-open followed by a crash produces exactly this and leaves no error anywhere. Open
  question: has anything written a zero-byte dossier SINCE that window.
- **`~/.claude/scripts/push-pr-fence.py` matches its trigger string anywhere in the command text**,
  so it refuses a heredoc whose body merely quotes the command in a document. It is a shared
  founder guard, so changing it is not a solo edit.
