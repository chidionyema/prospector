# ML / optimisation opportunity audit — 2026-08-15

**Question asked:** where can machine learning, advanced or otherwise, greatly improve or optimise
the engine?

**Method.** Eight parallel evidence passes over the code and `store/` on disk (funnel yield, cost
and latency, retrieval quality, dedup/prescreen, scoring and calibration, outcome labels,
eval harness and routing, and a prior-art sweep of the tracked programme docs), plus two
measurements run directly for this audit. Every number below carries the file, command or
sample that produced it. Anything not measured is marked HYPOTHESIS.

---

## 0. The three findings that frame everything

**(a) Cost is not the problem, so no proposal here is justified by token savings.**
Total metered spend is **$79.89 over 119 ticks, 2026-06-22 → 2026-08-15**
(`store/scheduler/batch_diagnostics.jsonl`, `by_provider` sum), and the all-in cost of one PASS
— every kill paid for along the way included — is **$1.011** ($79.89 / 79 passes), independently
cross-checked at **$0.994** against the lifetime ledger ($91.42 / 92 lifetime passes,
`store/prospector.jsonl`, 22,607 metered calls). The two agree within 2%.
Any ML pitch framed as "this saves money" is optimising a rounding error. **The levers that
matter are yield and quality.**

**(b) Most of the obvious ML ideas have already been tried here and killed on evidence.**
The prior-art sweep found a substantial experiment register already run. The pattern across it
is consistent and should govern what we propose next: **every attempt to substitute a small or
local model for an evidence-conditioned judgement has failed.** See §4 for the do-not-repeat list.

**(c) The engine deletes its own training data, so nothing can be learned from its history.**
After two months and 2,130 dossiers there are **zero (features, outcome) pairs** on disk. This
gates every supervised option in this document, which is why it is recommendation #1.

---

## 1. The funnel, measured

Source: `store/scheduler/batch_diagnostics.jsonl`, 119 batches summed, 2026-06-22 → 2026-08-15.

| Stage | In | Dropped | % dropped |
|---|---|---|---|
| generated | 1303 | — | — |
| dedup | 1303 | 2 | **0.15%** |
| rejection_fastpath | 1301 | 6 | 0.46% |
| prescreen | 1295 | 67 | 5.2% |
| novelty selection (budget cap) | 1228 | 39 | 3.2% |
| **verify — kill** | 1186 | 981 | 82.7% of decided |
| **verify — defer** | 1186 | 126 | 10.6% of vetted |
| **verify — pass** | 1186 | 79 | **6.66% of vetted** |

Independent cross-check on dedup from separate telemetry (`store/generation_metrics.jsonl`,
42 batches): 582 generated → 580 post-dedup, same near-zero magnitude.

### What actually kills a candidate (n=1,984 kill dossiers, `gate_fired` field)

| Gate fired | n | % of kills |
|---|---|---|
| **`min_composite` — the SCORE, not a hard gate** | **755** | **38.1%** |
| `moat_ungrounded` | 476 | 24.0% |
| `incumbency` | 255 | 12.9% |
| `adversarial_decisive` | 141 | 7.1% |
| `value_durability` | 117 | 5.9% |
| `source_or_die` | 81 | 4.1% |
| `payer_solvency` | 69 | 3.5% |
| all others (legality, distribution, pain_reality, 2nd-stage) | 90 | 4.5% |

Grouped, this is the load-bearing fact of the whole audit:

- **38.1%** die on an uncalibrated weighted sum (§2).
- **35.2%** (698 = moat_ungrounded + adversarial_decisive + source_or_die) die because the
  evidence was too thin to rule at all (§3).
- **25.2%** (499) die on one of the six named hard gates — an actual cited-evidence rejection.

**Only a quarter of kills are the engine doing the thing it exists to do.** Roughly three
quarters are "the score said no" or "we could not tell". That is where the yield is.

Integrity check, and it passes: passes stamped `provisional` = **0/68** — the rule that a
non-trusted brain never publishes on PASS (`run.py:864`) is enforced on disk, not just in code.

---

## 2. The six-axis score is one axis, and it is the modal kill gate

`prospector/score.py:19-22` computes composite = `Σ scores[axis] × weights[axis]`. The per-axis
scores are **LLM-emitted 0-5 rubric numbers**, not computed features (`score.py:38`
`_scorer.complete_json(...)`; `:40-41` clamps and rounds). Weights live at `config.yaml:493-498`
and were hand-set, with exactly **one** re-weighting event in the repo's history (`73ae976`,
2026-06-25) justified in prose by a single hand-picked counterexample — never fitted to data.

### Measurement run for this audit (n=842 scored dossiers, numpy on the correlation matrix)

Every pairwise correlation between the six "independent" axes is high:

```
                    pain  money  auto  distr  defens  build
pain_acuity         1.00   0.67  0.58   0.60    0.63   0.69
money_provability   0.67   1.00  0.53   0.58    0.58   0.64
automatability      0.58   0.53  1.00   0.53    0.55   0.78
distribution        0.60   0.58  0.53   1.00    0.59   0.62
defensibility       0.63   0.58  0.55   0.59    1.00   0.64
build_feasibility   0.69   0.64  0.78   0.62    0.64   1.00
```

PCA on that matrix:

| | eigenvalue | variance explained | cumulative |
|---|---|---|---|
| **PC1** | **4.078** | **68.0%** | 68.0% |
| PC2 | 0.553 | 9.2% | 77.2% |
| PC3 | 0.442 | 7.4% | 84.5% |
| PC4-PC6 | ≤0.409 | 15.5% | 100% |

- **PC1 alone explains 68.0% of the variance.**
- **Kaiser criterion retains 1 component of 6.**
- Effective dimensionality (exponentiated entropy of the eigenvalue spectrum): **3.08 of 6**.

And the weight vector is close to inert:

- Configured weights vs **equal** weights: Spearman **ρ = 0.9606**.
- Configured weights vs PC1: Spearman **ρ = 0.9687**.
- Replacing the hand-set weights with equal weights (rescaled to the same mean/sd) flips the
  PASS/KILL side of `min_composite = 2.5` for **36 of 842 candidates = 4.3%**.

**Reading.** The six-axis rubric is, to a very good approximation, one latent "is this idea any
good" judgement from the model, wearing six hats. The weight vector — currently fenced as a
moat-affecting knob — moves the ranking by ρ=0.96 and changes 4.3% of outcomes. Meanwhile
**24.9% of the scored population sits within ±0.3 of the threshold** (209/838), so a single
hand-picked constant, 2.5, is doing decisive un-fitted work on a quarter of the population.

Script: `scratchpad/pca.py`, reading the `score` block of `store/dossiers/*.json`.
Independently consistent with `prospector/critique.py:14`'s own note that `min_composite` is the
modal kill gate in 8 of 9 persona cells (measured on the 1,789-row index, 2026-08-08).

---

## 3. Retrieval: the constraint is query specificity, and ranking has a measured ceiling

Sample: 400 random dossiers / 1,912 checks, plus `store/scheduler/audit/*.jsonl`
(36,852 `search` + 1,143 `search_rank` events).

- **Availability is fine.** ddg 12,469 calls at **98.8% ok**; only **2.6-3.8%** of checks come
  back with zero sources; the first provider suffices **84.7%** of the time.
- **Relevance is the failure.** **77.9% of unverifiable checks (977/1,254) DID have cited
  passages** and still could not clear supported/refuted. The engine found evidence that was
  topically adjacent but not decisive for the narrow claim.
- Reranking already exists and is doing real work — `RelevanceRankedProvider`
  (`retrieval.py:442-495`) overfetches k×3 and sorts by term overlap: query-term coverage
  **34.4% → 42.3% mean** (+7.9pp, +23% relative), swapping ≥1 result in **80.6%** of calls.
- **But better ranking has a low measured ceiling.** Experiment E16's rerank-ceiling probe
  (`COMMERCIAL_READINESS_PROGRAM.md` §19.2) found only **37.9% all-eras / 40.8% current-moat**
  of cases are reachable at all, because **54.5% already had the best passage at rank 0** — the
  judge saw the best available evidence and still ruled unverifiable. **Do not lead with a
  cross-encoder.**

Unverifiable rate by check (1,912 checks):

| check | % unverifiable |
|---|---|
| **payer_solvency** | **80.2%** |
| legality | 75.9% |
| distribution | 70.0% |
| incumbency | 64.3% |
| pain_reality | 60.3% |
| value_durability | 58.7% |

This half-refutes the standing belief: payer_solvency is indeed worst, but value_durability is
**sixth**, behind legality and distribution.

Other measured facts: retrieval cache hit rate **2.8%** (457/16,130); **0 duplicate queries
across 4,309** query instances — cross-candidate evidence reuse is structurally near-zero,
by design, not by cache defect; **12.1% of cited URLs are dead** (285/2,353,
`store/lint_url_cache.json`).

---

## 4. Do not re-run these — already measured and closed

| ID | Idea | Result | Where |
|---|---|---|---|
| E6 | Local-embedding kNN prescreen prefilter, target ≥20% call reduction | **Safe drop rate 0.00%** over 1,789 candidates at any PASS-safe threshold; the next operating point drops 82.56% and loses **63.3% of PASSes**. Reproduced live: `would_drop=True` in **0/518** shadow rows. | `COMMERCIAL_READINESS_PROGRAM.md` §32.1 |
| W0.1 | Embedding + kNN distance to PASS/KILL centroids to predict the verdict before paying | Regime-restricted AUC: lexical **0.502**, `nomic-embed-text` **0.375-0.411** — at or below chance. (Higher unrestricted figures disqualified as leakage across a regime boundary.) | `ENGINE_WAR_PLAN_2026-08-13.md` Wave 0 |
| L1 | BM25/exact-key index to reuse evidence already paid for | **Recall@5 11.91%** vs a 20% bar; exact-key repeat 0.01%. | §29.2 |
| E13 | Proxy-framed claim reframe to recover unverifiable checks | Recovery **27.9%/29.2%** vs an 88% bar; shuffled control 12.5%. KILLED. | §23.2 |
| E17 | HHEM/MiniCheck entailment as an automatic verdict gate | AUC **0.673**; supported-arm agreement 52.8% with a negation confound pushing Δ **−0.0340**, the wrong way. | §28.8 |
| — | Decomposing checks into finer sub-claims | **−5.3 to −8.9** balanced-accuracy points with a strong verifier. | War plan "Cut" table |
| — | Embedding-distance KILL of ~50% of a wave | Cut on doctrine: "trains on the very composites it calls miscalibrated". | War plan "Cut" table |
| V4 | Meta-shape monitor (embed one-liners, k-means, alert on cluster share) | Ran: top cluster **17.65%** vs a 35% alert bar, 1,773 rows. **No mode collapse.** | §28.7 |

The through-line: **small and local models cannot do the evidence-conditioned judgement**, and
the engine has already paid to learn that seven times. Semantic *similarity* tasks are a separate
question (§6).

---

## 5. Recommendation #1 — stop destroying the labels (prerequisite for everything else)

This is not glamorous and it is not ML, but every supervised option in this document is blocked
on it.

| Would-be label | n | Why it is unusable |
|---|---|---|
| provisional → re-vet outcome pairs | **0** | `store.py:265-269` unlinks the stale decision file on every re-vet, and the DB does `INSERT OR REPLACE` on `candidate_id`. Verified: 0 candidate_ids carry both a `.kill.json` and a `.pass.json`. 180 live `provisional=1` kills exist, but the "before" state vanishes the moment any of them re-vets. |
| PASS later retracted (real delayed negative) | 20 archived + 15 unlist rows | **The outcome survives, the features are deleted.** Archive receipts carry only `candidate_id, title, market, verified_at, published_via, catalog` — no score, no axis vector, no confidence. |
| Human review decisions | **0** | `prospector/human_review.py:50` is fully built (backfill/list/show/decide); `store/human_review/` does not exist on disk, despite 92 eligible PASS dossiers. |
| Sales / revenue | **0** | `Orders`, `SalesAudits`, `Entitlements`, `PackPriceHistory` are all **0 rows**; production truth is on the Fly volume and not reachable from this repo. Analytics: 24 rows, all `page_view`, all dated 2026-08-01, dev traffic. |
| Golden set | **9** | 7 KILL + 2 PASS, and the evidence is explicitly **synthetic** (`fixtures/golden_fixtures.json` `_README`). A regression fixture, not a training set. |

**Do this:** make the decision log append-only. On every verdict and every re-vet, write an
immutable row carrying the candidate features, the full axis vector, the composite, the
confidence, the gate fired and the ruling brain — and never unlink it. Capture the retracted-pass
features *before* deletion, since retraction is the only true negative label the engine can
generate without a buyer. Cost: small. Payoff: it is the difference between "we could calibrate
this in three months" and "we still cannot, in three months".

---

## 6. Ranked opportunities that survive the evidence

### R1 — Fix the label pipeline (§5). Prerequisite. Not ML.

### R2 — Treat the score as the one number it measurably is
The finding in §2 is actionable without any new model:
- Stop spending effort tuning a six-weight vector that moves outcomes by 4.3% (ρ=0.96 vs equal
  weights). The leverage is in the **threshold** (24.9% of the population sits within ±0.3 of it)
  and in whether the rubric has any real dimensionality at all (effective dim **3.08 of 6**).
- The testable design question: can a redesigned rubric with genuinely orthogonal axes raise
  effective dimensionality? That is measurable offline on stored axis vectors, at zero token cost,
  the same way §2 was measured.
- Calibration proper (isotonic / Platt on the composite) is the right technique and is **blocked
  on R1** — there is nothing to calibrate against today. The one honest precedent, E11, moved the
  confidence floor 0.0 → 0.4 and freed **66/333 (19.8%)** of reproducible evidence kills; it was a
  percentile pick on a replayed distribution, not a fitted model, and it is the best calibration
  work in the repo.

### R3 — Finish E1: entity-templated queries on `payer_solvency`
The worst check (**80.2% unverifiable**) is the exact target of an experiment that was built,
fixed a real defect (payer queries: 38-word median → 15-word) and then **never had its live A/B
run because it hit the spend cap**; `hybrid_entity_checks: []` is empty at `config.yaml:113`.
E5's power analysis already says ~**6 batches per arm** on movable axes. At $0.067/candidate this
costs single-digit dollars. It is the cheapest unfinished experiment with the largest measured
target in the whole register.

### R4 — Turn on the diversity machinery that is already built and switched off
Generation is **66.7% of notional compute** ($2,758.76 of $4,135.26 claude_cli self-reported,
vs $1,362.59 for verification — generation costs ~2× verification) and carries the longest
latency (`generate` mean **238.4s**, p90 **706.4s**). It is also where the most built-but-inert
ML sits:

| Flag | State | What it is |
|---|---|---|
| `coverage_sampler.quality_weight` | **0.0** (inert) | G7 quality-weighted cell credit (QD/MAP-Elites-style) |
| `lane_quota_mode` | **static** | G9 empirical-Bayes shrinkage + uniform exploration reserve — a bandit, built, gated |
| `coverage_sampler.enabled` | **false** | V2 |
| `critique_revise.enabled` | **false** | G8 |
| G4 verbalized-sampling typicality | shipped, **inert downstream** | populated but "nothing is filtered, reordered or down-weighted" |

Nothing needs building. It needs enabling, one at a time, with E5's power analysis as the stopping
rule. Caveat: G9 is founder-fenced (venture is 0 PASS in 35) — that fence is a decision, not an
oversight, and should be confirmed before it moves.

### R5 — Re-open dedup as a *redundancy* problem (not a verdict-prediction problem)
Dedup currently drops **2 of 1,303 (0.15%)**. A hand-judged sample this session — the top 40 by
Jaccard of the 225 pairs sitting in the band the live thresholds miss (`dedup_threshold 0.85`,
`dedup_token_threshold 0.34`, run through the production functions, not a reimplementation) —
found **~22/40 (55%) are the same underlying idea reworded**, ~75% including template
cluster-mates. Stated honestly: that is a **ceiling-of-band estimate from a top-40 sample**, not
the rate across the band.

This is worth re-opening precisely because it is *not* the task that failed. E6 and W0.1 asked
embeddings to predict a verdict and got AUC ≈ 0.5. Redundancy detection is semantic similarity,
which is what embeddings are actually good at, and the repo's own on-box measurement supports it:
**cos(text, reworded) = 0.8374 vs cos(text, unrelated) = 0.4930, margin +0.3444**
(`config.yaml:1777-1779`, measured 2026-08-07).

Magnitude honesty: even 15% duplicates is ~195 candidates × $0.067 ≈ **$13 over two months**.
**This is not a money lever** — it is a shots-on-goal lever, and V4's finding of no catalogue mode
collapse (top cluster 17.65% vs 35%) weakens it further. Recommend an offline replay to establish
the true near-dupe rate against a labelled sample **before** any gate ships.

### R6 — The instrumentation defects that will corrupt any measurement you take next
Cheap to fix, and they poison every number downstream:
- **`telemetry.PRICING` has no `claude_cli` key** (`telemetry.py:186-191`), so `get_price()`
  (`:195-222`) silently returns $0 and **claude_cli reports $0.00 in the metered ledger** — the
  metered total understates by its largest component.
- **91.9% of ledger spend ($84.01 of $91.42) carries no `stage` tag**, so per-prompt cost
  attribution is impossible; both ledgers stop at `phase` granularity.
- **$28.17 across 2,817 calls is logged under provider `"?"`.**
- `score.py`, `artifacts.py`, `classify.py`, `critique.py`, `discover.py` have **no `operation=`
  latency wrapper** — invisible in the wall-time ledger.
- **Denylist bug, still live:** the string `"adversarial"` never matches the stored
  `"adversarial_decisive"` (`prospector/denylist.py:33`), excluding **142 kills** from kill-family
  clustering.

---

## 7. The constraint on doing any of this safely

**The offline harness is narrower than it reads.** The golden set is **9 synthetic cases**
(`fixtures/golden_set.json`), and `discrimination = correct / (total − deferred)` scores a
decision match only (`golden.py:128,208,249,343-344`). Fixture replay is real and free
(`golden.py:184-192`) — but `golden.py:540-548` sets `skip_adversarial=True` **unconditionally**,
because the adversarial gate runs at temp 0.3 and would override the checks being measured.

**Therefore: a change to hard-gate logic can be regression-tested offline for free. A change
touching the adversarial gate, the soft gates, generation quality, or the non-critical chain has
no offline harness at all and needs live paid runs.** Anything proposed above must say which side
of that line it falls on. R2 and R5's offline analyses fall on the safe side; R3 and R4 need live
runs, which is exactly why E5's power analysis (~6 batches/arm) matters.

**A related receipt gap, flagged not actioned.** `store/golden_runs/` holds 6 minimax runs, all
`total_runs: 1` — never a `--runs 3` invocation. Scores: 0.667, 0.778, 0.889, 0.667, 0.857, 1.0.
The 1.0 is timestamped **11:11:04, after** the 10:58:38 commit (`42909b2`) that cites "three
consecutive golden runs at discrimination 1.00" as its justification, and it is stamped
`model_version: fallback(minimax+claude_cli)`, not pure minimax. The 0.96 figure appears nowhere
on disk (`git log -S"0.96"` returns nothing).
**This is an evidence-recording problem, not grounds to revert the roster.** The scorer bug that
commit fixed is real and diff-verified (`verify.py:90`): the old `_calc_confidence` gave 70% of
its weight to citation fraction and domain count and 0% to model confidence. CLAUDE.md's standing
instruction not to revert MiniMax on a single failing run stands. The fix is to make the golden
harness write the receipt it claims, so the next roster decision has one.

**One live operational finding:** the **ollama daemon was not running** when this audit began
(`ollama list` → "timed out waiting for server to start"), so every dense-embedding path silently
degrades to `lexical`. It starts fine on demand (verified: `/api/tags` up in 1s,
`nomic-embed-text` 274MB / 768-dim returns embeddings). Anything in R5 depends on it being
supervised, not assumed.

---

## 8. Bottom line

The engine does not need a model. It needs to start keeping the data that would let one be
built, and to finish the three cheap experiments it already designed.

Sequenced: **R1 (keep the labels) → R6 (fix the meters) → R3 (finish E1 on payer_solvency) →
R2 (stop tuning a one-dimensional score, calibrate the threshold instead) → R4 (switch on the
diversity machinery, one flag at a time) → R5 (re-open dedup offline, ship nothing until the
replay says so).**

The "advanced" ML answer — learning the verdict or the score from real outcomes — is the right
long-run destination and is currently **unreachable**, not because the technique is hard but
because there are zero labels and zero sales rows on disk. R1 is what makes that question
askable at all, and until it lands, any proposal to train something here is a proposal to train
on nothing.

**Status: research and measurement only. No engine code changed by this audit.**
