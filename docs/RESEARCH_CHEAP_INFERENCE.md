# Research — making the verdict call cheap, 2026-08-20

Founder directive: make the engine 1000x better **and as cheap as possible to run**. Cost is a
target now, not an observation. This file is the research behind the cost half, plus the one
measurement that was run against our own corpus to check it.

Companion files: `docs/ENGINE_BASELINE_2026-08-20.md` (what the engine measures today),
`docs/RESEARCH_EVIDENCE_RECALL.md` (the retrieval half), `docs/COST_PROGRAM.md` (the ledger).

**Read the correction in section 5 before acting on section 4.** The research named a
"largest single lever" and our own corpus says it is the smallest one on the list. That
disagreement is the most useful thing in this document.

---

## 0. The number we are trying to move, and why it is not a meter reading

$3.60 per 1000 verdicts. **That figure is an ESTIMATE, not a measurement**, and the arithmetic below
is sound for RANKING the levers, not for claiming a saving after the fact.

**CORRECTED 2026-08-20.** This section previously said A6 was `UNOBTAINABLE` because "no ledger row
in 245 carries a cost field". That was measured against the wrong store. The canonical ledger,
`/Users/chidionyema/Documents/code/prospector/store/prospector.jsonl`, has 528 rows of which 39
carry `cost_usd`. A partial meter has existed the whole time.

**It is partial in the way that matters, so item 1.3 still ships first.** Three limits, all
measured (detail in `docs/ENGINE_BASELINE_2026-08-20.md`, finding 1):

- **It is blind to the head brain.** All 39 priced rows carry `message: "Claude CLI usage"`. 74
  rows mention minimax; **0** carry a cost field. The meter prices the fallback, not the primary.
- **The figure is notional.** `cost_usd` is the Claude CLI's own retail number on a subscription
  already paid for — what the work would cost at API prices, not cash out.
- **It is the wrong host.** Those rows span 84 minutes of local laptop runs.
  `com.prospector.scheduler` is off by design here; the engine has run on Fly since 2026-08-18.

What the partial meter does give is a scale check on the estimate, and the two do not agree.
Measured median **$0.1893 per candidate vetted** — $189 per 1,000 vets, against an estimate of
$3.60 per 1,000 verdicts. A vet is 3–6 calls, so the units are not identical, but no reconciliation
of them closes a 50x gap. **Do not quote either number as the baseline until 1.3 lands and prices
a MiniMax call.** Every percentage below remains a projection.

Measured inputs that the arithmetic rests on, all from `tools/engine_baseline.py` against the
2026-08-19 snapshot (fingerprint `d66f09d0544fd796`, 2806 dossiers, 14006 checks):

| Input | Value | Where |
|---|---|---|
| model calls per vet, mean | 4.991 | cost anatomy |
| model calls per vet, median | 6 | cost anatomy |
| full six-check vets | 50.6% | cost anatomy |
| evidence chars, median | 1500 | cost anatomy |
| evidence chars, mean | 2878 | cost anatomy |
| preamble | ~11,250 chars ≈ 2,813 tokens | E-103 |

**The preamble is 88.2% of input tokens** (2,813 of ~3,188). That single ratio decides which levers
are worth pulling: anything acting on the preamble is worth up to 8x more than anything acting on
the evidence. Prompt compression of the evidence can only ever reach the other 11.8%.

---

## 1. The trap that would have cost us the whole caching saving, silently

**Claude Haiku 4.5's minimum cacheable prefix is 4,096 tokens. Ours is 2,813.**

A `cache_control` block on a prefix below the minimum is not an error. The API accepts the request,
returns 200, reports `cache_creation_input_tokens: 0`, and bills every call at full price forever.
Nothing in a log, a dashboard or a test would show it. We would have "enabled caching", measured no
change, and concluded caching does not work for our workload.

Minimums, as published:

| Model | Minimum cacheable prefix | Our 2,813-token preamble |
|---|---|---|
| Claude Haiku 4.5 | 4,096 tokens | **below — caching silently inert** |
| Claude Sonnet / Opus | 1,024 tokens | above — works |
| Gemini 3.x Flash | 4,096 tokens | **below — caching silently inert** |
| Gemini 3.x Pro | 4,096 tokens | below |

The counterintuitive consequence, and the reason this section is first: **padding the preamble UP to
4,096 tokens makes it cheaper.** More tokens, less money, because the cache discount applies to all
of them instead of none. On Haiku that is $4.69 → $2.29 per 1000 verdicts.

The padding must be real content in a stable prefix — the check definitions, the verdict rubric, the
worked examples — not filler. Filler that changes between calls would break the prefix match, which
is the same failure by another route.

**Guard, not a note.** This is exactly the class LAW 6 says to close mechanically: a
misconfiguration that reports success. Whatever we ship must assert
`cache_read_input_tokens + cache_creation_input_tokens > 0` on the second call of a run and fail
loudly if it is zero. A caching config with no assertion is a caching config that is off.

---

## 2. The levers, ranked, with what each is worth

Baseline $3.60 per 1000 verdicts. Each row assumes the ones above it are already applied.

| # | Lever | Effect | Independent? | Risk |
|---|---|---|---|---|
| 1 | Prompt caching on a stable preamble | up to 90% off the 88.2% | yes | the §1 trap |
| 2 | Merge the six check calls into one | 4.991x fewer calls, 2.8x fewer tokens | yes | quality — needs a golden gate |
| 3 | Batch API | further 50% | stacks with 1 on Anthropic and Gemini | 24h latency |
| 4 | Deterministic no-model prefilter | **4.69%, see §5** | yes | none by construction |

Items 1 and 2 together take $3.60 to roughly $0.19 per 1000 — about **19x, from configuration
alone, with no model swap and no quality decision**. That is the headline.

**Batching does not stack everywhere.** On Anthropic and Gemini the batch discount and the cache
discount compose. On Groq the batch discount REPLACES caching rather than adding to it, so
enabling both there buys one discount and the illusion of two.

**24h latency is a real constraint, not a footnote.** The batch route fits the scheduled drain,
which already tolerates deferral by design. It does not fit an on-demand vet, where a founder is
waiting. Any batching we ship has to be per-lane, and the on-demand lane keeps the synchronous
path.

---

## 3. Open verifiers we are actually allowed to use

E-101 already answered the big version of this question and the answer was no: the best free
model separated a cited passage from an unrelated one at 0.706 AUC, one arm scored 0.408 (below
random), and throughput was 0.04 pairs/s on rented CPU. **Nothing below overturns that.** These are
listed because licence terms are the part that is expensive to rediscover.

**Commercially usable:**

| Model | Licence | Size | Notes |
|---|---|---|---|
| MiniCheck-Flan-T5-Large | MIT | 0.8B | fact-checking specific |
| HHEM-2.1-Open | Apache 2.0 | 0.1B | 600 MB, runs on CPU, ~1.5s per 2k tokens |
| Granite Guardian 3.3 8B | Apache 2.0 | 8B | 76.5 on its benchmark vs GPT-4o's 75.9 |

**Barred — non-commercial licences.** Bespoke-MiniCheck-7B and Paladin-mini top the public
leaderboards and **cannot be used by this business at all.** They are named here so that the next
session reading a leaderboard does not spend a day on them before reading the licence file. This
is the trap worth remembering out of the whole section.

---

## 4. Do not rent a second box

Breakeven for a Fly `performance-1x` at $32.19/mo, against the API cost AFTER items 1–3 land, is
**169k–346k verdicts/month**. Lifetime throughput is 1.844 dossiers/hour (A2), so we are three
orders of magnitude below breakeven.

This is LAW 14's operational-vs-one-off distinction doing its job: a rented box is an OPERATIONAL
cost that bills forever and would replace an API bill we are about to cut by 19x. Swapping one for
the other is not a saving.

---

## 5. E-105 — the correction, and it is the important part of this file

The research named item 4 the **largest single lever**: a deterministic prefilter that answers an
`unverifiable` check with no model call whenever no passage was retrieved, or no entity or number
from the check's own queries appears anywhere in what came back. The reasoning was that our 73.3%
abstention rate is mostly evidence that was never there.

That is a claim about OUR corpus, and our corpus is on disk, so it was measurable rather than
arguable. `tools/experiments/e105_unverifiable_prefilter.py`, one pass over 14,006 checks:

| Result | Value |
|---|---|
| `unverifiable` checks | 10,265 |
| catchable with no model call | **481 — 4.69%** [4.29, 5.11] |
| — no source retrieved at all | 293 |
| — sources retrieved, zero token/number overlap | 188 |
| not decidable without a brain | 9,784 |
| **control: same rule fired on RULED checks** | **10 of 3,741 — 0.27%** [0.15, 0.49] |

**The lever is real and it is small.** The control is what makes both halves of that sentence
trustworthy: the Wilson intervals for the real rate [4.29, 5.11] and the false-positive rate
[0.15, 0.49] do not overlap, so the rule is detecting absence of evidence rather than some
property of our own prose. It just does not fire often. 481 saved calls is 3.4% of all checks,
not a headline.

**What the same pass found instead, and it reframes the abstention problem.** 9,784 unverifiable
checks — 95.3% of them — DID have passages in hand that shared entities or numbers with the query.
The evidence came back topically related and the brain still declined to rule.

So the bottleneck is not that the web lacks the answer, and it is not only how we query. It is what
happens between a topically-relevant passage and a verdict. That is a prompt-and-rubric problem, and
it sits on the same call that items 1 and 2 are about to rewrite anyway.

**Two angles that disagreed (LAW 15).** The retrieval research and AVeriTeC's 6.2–9.2% human NEI
rate said our 73.3% was a querying failure. E-105 says 95.3% of the abstentions had relevant text
already retrieved. Both cannot be the whole story. The third measurement that decides it is the
human-labelled set — action plan item 1.2 — because it is the only instrument that can say whether
those 9,784 checks were correctly unverifiable or wrongly abstained. **Until that exists, nobody
should claim the abstention rate is a defect OR that it is correct.** The baseline's "73.3%
abstention is our defect" line is hereby downgraded to a hypothesis with a named test.

**The prefilter is still worth shipping**, at its true size. It has zero accuracy cost by
construction, not by measurement: it can only ever emit `unverifiable`, which is what the engine's
own rule already requires when there is no matching passage. It generalises the constraint
`price_comparables` already enforces. It is a small, free, safe win — which is a different thing
from the biggest one.

---

## 6. What to do, in order

1. **Ship the cost meter first** (action plan 1.3). Sharpened 2026-08-20: the gap is not that no
   row carries a cost — 39 of 528 do — it is that **no MiniMax row does**, and MiniMax is the head.
   The specific deliverable is a `cost_usd` on every metered adapter's row, priced from the
   provider's own published rate where the adapter does not report one, plus a `provider` field so
   the join does not depend on parsing `message`. A 19x claim measured only on the fallback brain
   cannot be verified after the fact.
2. **Cache the preamble, padded to 4,096 tokens, with the assertion from §1.** Biggest lever,
   no quality decision, and the assertion is what stops it being silently inert.
3. **Merge the six check calls behind the golden gate.** 4.991x on calls. This one CAN change
   quality, so it does not ship without a gate run — and the gate's own instrument is saturated
   at 1.00 on nine items, so use gate accuracy (44.4% stored, 78% live) as the reading that moves.
4. **Ship the E-105 prefilter at 4.69%.** Small, free, safe.
5. **Batch the scheduled drain only.** Leave on-demand synchronous.
6. **Do not rent a box. Do not swap the brain on price alone** — E-101 already priced that at
   0.706 AUC.

Items 1–4 project $3.60 → ~$0.06 per 1000, about **60x**, with no model-quality decision and no new
hardware. Item 1 is what makes that sentence checkable instead of merely encouraging.
