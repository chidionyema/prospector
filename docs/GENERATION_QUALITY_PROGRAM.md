# Generation Quality Programme (Tier 1 + Tier 2)

> Branch `feat/generation-quality-tier12`. Goal: raise the intrinsic quality and value of
> GENERATED ideas — never loosen gates, never reframe claims, never optimise the pass rate
> directly (founder directive 2026-08-08: kill stats are a report card on the generator,
> not a target). "Creativity lives in generation; constraint lives in verification" stands:
> nothing here kills at generation time.

## Diagnosis (measured on the live store, 2026-08-08 session)

Three generation defects, from a 548-dossier August sample:

1. **Market-incumbency blindness** — the generator knows its own history (~120-title avoid
   list) but nothing about the market; incumbency (206) + value_durability (85) kills are
   the moat discovering, at full verdict price, facts a $0 bounded search would have shown
   the generator up front.
2. **Meta-shape convergence** — despite an 8-form x 13-persona matrix, ideas converge on a
   few consensus shapes; the only diversity forcing is prompt text plus one DPP subset.
3. **Wedges asserted, not designed in** — durable_wedge_type is claimed at generation and
   refuted at verification (value_durability kills).

Persona choice moves PASS ~9x (smb_owner 9% vs freelancer 1%) yet quotas are uniform.

## Research basis (verified 2026-08-08)

Persona partitioning + CoT beats human ideation diversity (arXiv:2602.20408). Verbalized
Sampling ~2x diversity at equal quality (arXiv:2510.01171). Denial prompting drives
constraint-led novelty (arXiv:2407.09007). ONE critique->revise pass helps, iterating does
not (arXiv:2507.08350). QDAIF: archive over descriptor cells + fitness (arXiv:2310.13032).
Judged novelty is inflated — never optimise it (arXiv:2506.20803); variance, not mean, is
what an idea filter monetises (arXiv:2402.01727). Distinct-k as the diversity metric
(arXiv:2504.05228). Anti-levers (measured failures elsewhere): multi-agent debate,
temperature tuning, pseudo-panels of correlated judges.

## Design rules

- **Golden-safe:** every feature is config-gated and code-defaults OFF; `config.yaml` in
  this branch flips on the ones we ship. Default behaviour is byte-for-byte current.
- **Fail open:** no generation-side feature may ever stop the daemon generating
  (coverage.py's `plan_cells` returning `[]` is the pattern).
- **Deterministic where possible:** G1/G3/G5/G9 are zero-LLM, pure functions of the store.
- **All state under `cfg.store_dir`** so tests never pollute production state.

## The build items

Status vocabulary — `built` means the code is on this branch AND its tests are green in
the suite; `specified` means the row below is a design, not a shipped thing. A row is
never marked `built` from intent. Nothing here is `proven`: proof is a daemon receipt in
`store/generation_metrics.jsonl`, and none has been taken yet.

| id | item | mechanism | status |
|----|------|-----------|--------|
| G1 | Distinct-k diversity meter | `prospector/diversity.py`: per-batch distinct-k (greedy clustering on dedup's content-token Jaccard, threshold 0.34), mean/max pairwise overlap, per-axis entropy (form/audience/market/tier). Receipts appended to `<store_dir>/generation_metrics.jsonl` at stages `generated` and `post_dedup`. Gate: `generation.diversity_meter`. | built |
| G2 | Incumbent-landscape seed enrichment | `prospector/landscape.py`: ONE bounded, cached (ttl 7d, keyed on topic x market) retrieval per generate call -> an `INCUMBENT LANDSCAPE` block injected into the generate prompt, appended in Python (`prompts.render` cannot take new placeholders — it does not raise on unsubstituted ones, `prompts.py:163-201`). Providers are `ddg,exa` only: `claude_cli` is stripped with a warning so a generation query can never queue ahead of a moat verdict. CONTEXT, never evidence — never cited, never scored, cannot kill. Fails open to "". Gate: `generation.incumbent_seed.enabled`. | built |
| G3 | Kill-family denial constraints | `prospector/denylist.py`: mine the FULL kill corpus (not a 20-row window) into standing exhausted families (>=3 kills on `value_durability`/`incumbency`/`adversarial`, clustered by content-token Jaccard). Cached in `<store_dir>/exhausted_families.json`, refreshed when kills grow by 25. Appended to failure modes. Decay-proof: the window forgets, the denylist does not. Gate: `generation.denylist.enabled`. | built |
| G4 | Persona widening + Verbalized Sampling | Descriptions for the 5 undescribed business personas that rendered as bare slugs (`generate.py` `_AUDIENCE_DESCRIPTIONS`, lifted to module level). `prospector/sampling.py`: each idea self-reports a `typicality` in [0,1] and at least `ceil(k * min_atypical_fraction)` of the batch must sit at or below `atypical_threshold`. The self-report is NEVER a filter — an atypical idea is not a better idea; the number is carried into `tags.typicality` purely so `diversity.batch_report` can measure whether the directive actually moved the batch. Gate: `generation.verbalized_sampling.enabled`. Differentiate-rewrite is folded into G8. | built |
| G5 | Seed provenance + survival analysis | `tags.seed_kind` (`signal` \| `blue_sky`) stamped at the one place every accepted candidate passes through (`generate.py`, after the dedup/diversity passes — an earlier stamp survives on some paths and not others). Surfaced as `Candidate.seed_kind` and indexed as a `dossiers.seed_kind` column, same tag→property→column shape as `audience`. `tools/generation_survival.py` groups the index by any of seed_kind / audience / structural_form / ambition_tier / market and reports ruled-rows, pass rate, mean composite and modal kill gate. Zero-LLM, read-only. DEFER and provisional rows are excluded from the denominator; pre-migration rows stay `unknown` and are never redistributed. | built |
| G7 | Coverage sampler illumination | `coverage.py`: a cell counts as covered to the degree its ideas are GOOD, not merely numerous — `credit(v) = count(v) * ((1-qw) + qw * stat(v)/best stat)`. Both per-cell statistics (`elite` = max composite, `mean_composite`) are measured always and appear in the receipt; only STEERING is gated, on `coverage_sampler.quality_weight` (0.0 = V2 exactly, including the seed). `quality_stat` defaults to `mean`, **not** the QD-canonical `elite`, on a live measurement — see the chunk E entry. Statistics come only from RULED, non-provisional rows. Note the polarity: this steers TOWARD the worst-performing cells, the opposite of G9. | built |
| G8 | Critique->revise single pass | `prospector/critique.py`. ONE critique call (temperature 0.4) naming the weakest **composite axis** per idea, then ONE revision call (0.5) rewriting to remove that named weakness. Matching is by an injected integer `idx`, never by title — rewording the title is the point of a revision, so title-matching is structurally unusable. Strictly non-lossy **in code**: `len(out) == len(in)` is asserted and any index the model drops, duplicates or returns unparseably keeps its ORIGINAL. The axis brief renders from `config.yaml weights`, so a re-weighting moves the critic the same day it moves the scorer. Gate: `generation.critique_revise.enabled` (default off). When on it **replaces** the refine wave; it does not stack on it. | built |
| G9 | Measured lane quotas | `prospector/lane_yield.py` + `run.py` `_lane_counts` mode `measured`: expected composite per RULED candidate, shrunk toward the global mean by a 20-pseudo-row prior, plus a uniform 20% exploration reserve and a floor of 1/lane. Apportioned largest-remainder to exactly the static total, so the mode changes where candidates land and never how many are generated. Gate: `generation.lane_quota_mode`, default `static`. **This is the one item that points a lever at the kill stats — read the guardrails in `lane_yield.py`'s docstring before enabling it.** | built |

## Status ledger

- 2026-08-08: branch created off main + merged `fix/kill-log-smoke-selectors`,
  `fix/live-smoke-checks-log-selectors` (both verified clean with `git merge-tree`).
  Spec written. Implementation dispatched in chunks (A: G1+G3+G4-personas,
  B: G2+G4-VS, C: G5+G9, D: G7+G8), each verified with pi_gate + pytest before commit.
- 2026-08-08: chunk A committed (`f659272`) — G1, G3, G4-personas. POPDD gate green.
- 2026-08-08: chunk B committed — G2, G4-VS. G2 shipped with a defect found during
  verification and fixed before commit: the daemon's own call is
  `run_signal("", cfg=cfg, k=batch_size, publish=True, lanes=lanes)`
  (`scheduler/run_scheduled.py:723-724`) — **empty signal and no sector** — so the
  original two-rung `_topic()` returned `""` and G2 would have been inert on the majority
  of all generation, firing only on on-demand `vet` runs. `landscape._topic` now has a
  third rung, the audience persona slug, and
  `tests/unit/test_generate_prompt_wiring.py::test_blue_sky_run_still_gets_a_landscape_brief`
  pins it. Be honest about what rung 3 buys: a BUYER-level landscape, weaker than a
  signal-derived one. This is the "measure lever AUTHORITY first" lesson applied — a
  feature with no reach over the dominant path is a no-op however well it is built.
- 2026-08-08: chunk C committed — G5, G9. Full suite `2401 passed, 5 skipped`.

  **First measurement out of G5, on the live 1789-row index** (read-only, via
  `tools.generation_survival`, `min_n` as shown). These are the numbers the programme was
  built to be able to produce at all; every one of them is a report card on the GENERATOR:

  ```
  by ambition_tier              ruled  pass    rate  mean_c  top_kill_gate
    growth                         97    13   13.4%   2.179  min_composite
    side_hustle                   166    17   10.2%   1.812  min_composite
    venture                        68     6    8.8%   1.662  incumbency
    smb                           146     8    5.5%   2.039  moat_ungrounded
    unknown                       976    35    3.6%   0.852  min_composite

  by audience (min_n 40)        ruled  pass    rate  mean_c  top_kill_gate
    gen_z_worker                  202    19    9.4%   1.437  min_composite
    manual_tradesperson           147    12    8.2%   1.262  min_composite
    smb_owner                     222    18    8.1%   1.283  min_composite
    primary_carer                 187    14    7.5%   1.025  min_composite
    squeezed_middle               114     7    6.1%   1.071  min_composite
    retiree_cohort                105     3    2.9%   1.081  min_composite
    public_sector_worker          146     3    2.1%   0.895  min_composite
    unknown                       172     2    1.2%   1.331  value_durability
    freelancer_creative           142     1    0.7%   0.842  min_composite
  ```

  Two things to read carefully, and one trap:

  * **The persona spread is 13x** (gen_z_worker 9.4% vs freelancer_creative 0.7%) on
    comparable volumes — 202 vs 142 ruled rows, so this is not a small-sample artefact.
    That is a generation problem, not a gate problem: the same six checks at the same bar
    are being applied to both.
  * **`min_composite` is the modal kill gate in 8 of the 9 persona cells.** These ideas are
    mostly not dying on a hard gate at all — they are surviving the gates and then scoring
    too low to be worth publishing. That points the remaining work (G7, G8) at raising the
    ceiling of an idea rather than at anything to do with the gates, and it is direct
    evidence for the founder's "improve the IDEAS, not the kill rate" framing.
  * **The trap:** `smb` has the second-highest mean composite (2.039) and the second-lowest
    pass rate (5.5%), and its modal gate is `moat_ungrounded` — a retrieval outcome, not an
    idea outcome. Do NOT read that cell as weak generation until the grounding rate for it
    is separated out. This is exactly why G9 ships default-OFF: a value-weighted quota run
    today would move budget on a number that partly measures the retrieval layer.

  `unknown` is the 976 pre-migration rows, which stay unattributed by design — inferring
  their provenance from `created_at` would manufacture data.

### Chunk D — G8 critique -> revise (commit TBD)

* **The premise this doc shipped was wrong, and checking it changed the design.** The G8 row
  above previously said the pass "replaces the retired refine-wave". `_refine_wave` is not
  retired: `prospector/generate.py:408` is live, batched, and was *fixed* on 2026-07-02, not
  removed. So G8 is not filling a hole; it is replacing a pass that already runs.

* **The actual defect, found by reading the prompt the live pass uses.**
  `prompts/refine.md` was five lines and said, verbatim, **"Drop the weak/obvious ones."**
  `prompts/refine_system.md` carried a section headed **"THE KILL LIST (Ideas to drop)"**.
  The CODE was made non-lossy after the 2026-07-02 incident; the PROMPT never was. The way
  that contradiction resolves is the bug: an idea the analyst decides to drop is simply not
  returned, and the non-lossy guarantee then passes it through **unrefined**. Refinement was
  therefore *anti-targeted* — the ideas judged weakest received exactly zero improvement.
  Both prompt files are rewritten in this chunk to repair rather than remove, which is a
  behavioural change on the DEFAULT path (the only non-golden-safe change in the programme)
  and is justified by it bringing the prompt into line with a hard invariant the code has
  enforced since 2026-07-02.

* **The second defect: the refine prompt never mentioned the scoring axes.** Given that
  `min_composite` is the modal kill gate in 8 of 9 persona cells (chunk C's measurement
  above), the pass meant to raise an idea's ceiling was blind to what determines that
  ceiling. `critique._axes_brief` renders the axes and weights from `cfg.weights`,
  heaviest-first, so the critic cannot drift from the scorer — pinned by
  `test_a_reweighting_changes_the_brief_without_a_code_change`.

* **ONE round, and it replaces rather than stacks.** arXiv:2507.08350 finds the gain is in
  the first critique-revise round and that further rounds regress toward the model's own
  priors. Stacking refine-then-critique would also re-introduce the anti-targeting above,
  so `_refine_wave` returns early when the gate is on
  (`test_the_gate_on_replaces_the_refine_pass_rather_than_stacking_on_it`).

* **Thin candidates are now included.** The `< 50 chars` skip was a heuristic for a pass that
  could drop things; a two-word candidate is the clearest case for a critique. Under the gate
  they are critiqued; under the default path the existing skip is untouched.

* Cost, MEASURED rather than reasoned (`tools/experiments/g_generation_ab.py --fixture`,
  1 signal x 1 repeat, k=6): baseline `{generate: 6}` = 6 calls per wave, G8 arm
  `{generate: 6, critique: 1, revise: 1}` = 8. So the honest figure on the SHIPPED config
  is **+2 calls per wave, not +1**: the earlier "+1 (1 -> 2)" assumed the refine call it
  replaces was being paid, and `config.yaml:730` sets `refinement_enabled: false`, so it
  is not. Where refinement IS enabled the delta is +1. No verdict, retrieval or gate is
  touched either way.

* **G8 was a DEAD LEVER until this measurement.** Its gate sat after the
  `refinement_enabled` early return in `_refine_wave`, so on the only configuration that
  actually runs, critique->revise could never fire. Every unit test missed it because
  every one of them set `refinement_enabled: True`. The gate now precedes that return,
  on the reasoning that the two flags name different mechanisms — `refinement_enabled`
  is a judgement about the lossy refine pass, not a standing ban on improving a draft —
  and `critique_revise.enabled` remains its own explicit opt-in, default off. Pinned by
  `test_g8_still_fires_when_the_old_refine_pass_is_switched_off` and its converse.
  The general lesson is the one already in memory as `rsi-tuned-a-lever-with-no-authority`:
  measure a lever's AUTHORITY before measuring its effect.

* Receipts: `ruff check prospector tools tests` -> `All checks passed!`;
  `pytest tests/unit/test_critique_revise.py tests/invariants/test_house_voice.py
  tests/unit/test_gen_quality_regression.py -q` -> `44 passed`. Full-suite receipt in the
  commit message.

* **Not proven.** Nothing in this chunk has a daemon receipt. `enabled: false` is the honest
  default; the milestone that would change the status to `proven` is a live tick emitting
  `store/generation_metrics.jsonl` with distinct-k measured gate-on vs gate-off.

### Chunk E — G7 coverage illumination (commit TBD)

The premise the row in the table used to carry was PASS-yield weighting: feed the cells that
already pass. That is a pass-rate lever, which this programme is barred from building, and it
is also the wrong direction — the generator cannot learn anything from a cell it stops
attempting. What shipped steers the OPPOSITE way: a cell whose ideas score badly is treated as
*under*-covered however many rows it has, so the sampler spends more attempts there, not fewer.

The justification is that a row count cannot tell a barren cell from a badly-attempted one,
and this repo has already been wrong about exactly that once: `smb`'s modal kill gate turned
out to be `moat_ungrounded`, a retrieval outcome, not a verdict on the segment.

* Mechanism: `credit(v) = count(v) * ((1 - qw) + qw * stat(v) / best_stat)`, `qw =
  `coverage_sampler.quality_weight` (clamped to [0,1] — a typo must never stop generation).
  At `qw = 0.0` the sampler is V2 byte-for-byte, including `fingerprint()`: the elites are
  deliberately NOT hashed in, so turning measurement on cannot silently reseed the plan.

* Both statistics are MEASURED always and both appear in the receipt (`elite`, `ruled`,
  `mean_composite`); only STEERING is gated. Statistics come only from ruled, non-provisional
  rows (`decision IN ('pass','kill')`, `provisional = 0`) — a provisional row is by definition
  a verdict we do not trust, and a `defer` is a row we never ruled at all. A NULL composite is
  absent, never zero.

* **`quality_stat` defaults to `mean`, not to the QD-canonical `elite`, on a measurement**
  (live index, 1,789 rows, 2026-08-08, cells with n >= 30):

  ```
  ambition_tier   max: 3.050-3.550 = 1.16x    mean: 0.852-2.179 = 2.56x
  audience        max: 2.950-3.550 = 1.20x    mean: 0.842-1.437 = 1.71x
  ```

  Shipping `elite` alone would have been a lever with no authority: illumination lands in
  0.77-1.00 for every cell, so a weight of 1.0 barely reorders anything. The cause is
  structural, not a property of this snapshot — the maximum is an extreme order statistic and
  has converged over 40-110 samples per cell. `elite` is kept selectable because on a sparse
  or newly-split axis it has not converged and the max is then the more honest signal.

* Silence is not evidence: a cell value that has never been ruled gets illumination 1.0 (no
  penalty for being new), and if no cell has a positive statistic the whole weight goes inert
  rather than dividing by zero.

* Backward compatible on the index: `_table_columns()` PRAGMA-checks for
  `composite`/`provisional`/`decision`, so an index predating them is still MEASURED for
  coverage instead of refusing to measure.

* Receipts: `ruff check prospector tools tests` -> `All checks passed!`;
  `pytest tests/unit/test_coverage_illumination.py tests/unit/test_coverage.py -q` ->
  `50 passed`. Full-suite receipt in the commit message.

* The collection failure this chunk caused, recorded because the class of mistake will recur:
  the two new keys were rejected by the `coverage_sampler` allow-list in
  `prospector/config.py:349`, which every targeted test missed because targeted tests build
  their own fixture config and never load `config.yaml`. **A new config key is not shipped
  until something loads the REAL `config.yaml`.**

* **Not proven.** `quality_weight: 0.0` ships inert. The milestone is a live sampler run with
  the weight above zero and the resulting cell plan compared against the V2 plan.

### Chunk F — the A/B harness itself was measuring wrong (2026-08-08)

The first live proof run (`--signals 2 --repeats 2 --k 6`, 180 calls) reported
`shipped -6.00` and `g8_critique_revise -1.50` on distinct-k and stamped itself
`complete: true`. **Both numbers were an outage, and the run should be treated as
retracted.** Two defects in the harness, each verified from the receipts rather than
reconstructed from the story:

* **An empty batch was recorded as an observation.** The run hit the Claude usage wall.
  The wall does not raise through `generate()` — it logs `"Claude CLI skipped: usage wall
  is live"` (`prospector/claude_cli.py:270`) and returns `[]` — so the harness's
  `except ProviderExhaustedError` / `except Exception` fence never fired.
  `batch_report([])` returns a well-formed `distinct_k=0, n=0`, which entered the paired
  deltas as a real `-6`. 5 of the 24 cells were `(0, 0)`: all four `shipped` cells and one
  `g8_critique_revise`, reproducing the published figures exactly (4 pairs x -6 = -6.00;
  1 of 4 x -6 = -1.50). The empties were a contiguous TAIL in `ARMS` order, which is what
  rules out "the shipped arm is broken" in favour of "the wall opened mid-run".
  Fixed: `_run_cell` raises `EmptyBatch` (carrying its call count, so an aborted cell still
  reports what it cost); the caller banks the spend, discards the cell and sets
  `complete = False`. The module docstring had asserted this rule since the file was
  written — **a docstring stating an invariant is a claim, not a mechanism.**

* **`distinct_k` was saturated and could not discriminate.** All 19 non-empty cells scored
  exactly `6/6` (`raw` histogram `{(6,6): 19, (0,0): 5}`). The metric is capped at `k`, so
  every delta was `0.00` by construction — which reads as a confident "no lever does
  anything" when the truth is "the ruler hit its ceiling". `mean_pairwise_overlap` over the
  same cells did vary (0.043-0.075), so the run was ranked on the one metric that could not
  speak. Fixed: `_distinct_k_saturated()` gates the report, which now prints a `SATURATED`
  banner, tags the row `[saturated - not evidence]`, ranks on `mean_pairwise_overlap`, and
  writes `distinct_k_saturated` + `primary_metric` into the receipt. Saturation keeps exit
  code 0 (overlap is still valid); only an abort is non-zero.

* **The fixture could not have caught the saturation.** At k=6 fixture cells score 4/6, 3/6,
  5/6 — healthy headroom. Saturation was a property of live data only. A fixture proves the
  arithmetic; it never proves the headroom. Choose `k` from a fixture's `distinct_k=x/k`
  column before paying: at `--k 12` live and fixture cells both sit well below the ceiling.

* Receipts: `ruff check` -> `All checks passed!`;
  `pytest tests/unit/test_g_generation_ab_harness.py -q` -> `8 passed`, which pins both
  defects including `test_the_2026_08_08_outage_shape_would_now_abort` (replays
  batches-then-empties, asserts `complete is False` and that no recorded cell has `n == 0`).
  Fixture re-run at `--k 12` -> `COMPLETE`, 200 calls, no saturation.

* **The fix validated itself on live data, immediately.** The k=12 re-run
  (`--signals 2 --repeats 2 --max-calls 260`, 2026-08-08 08:36Z) aborted on its FIRST cell:
  `MEASUREMENT ENDED EARLY: baseline ...#0: generation returned 0 of 12 candidates after 16
  call(s)`, exit 1, `PARTIAL`, `no paired observation` on all five arms, 16 calls spent. Under
  the old code this same situation produced 24 recorded cells and two publishable-looking
  numbers. The cause was **not** the usage wall but a third rail: `api_error_status: 429`,
  `"You've hit your monthly spend limit"`. `errors.looks_exhausted` -> True and
  `classify_exhaustion` -> `permanent`, so `claude_cli` took a 1h dead mark in
  `store/provider_health_noncritical.json` — the daemon is blocked on the same limit, not just
  this harness. Note `usage_wall.looks_like_wall()` returns **False** for that text, so
  `is_blocked()` is not a valid preflight for it.

* **Still not proven.** The harness is now trustworthy; the levers are not yet measured.
  G7/G8/G9 stay off until a COMPLETE live run at `k >= 12` shows an effect. That run is
  blocked on the monthly spend limit being raised or reset — it is not blocked on any code.

## What is deliberately NOT here

Anything that moves the verification bar: confidence-floor changes, claim reframing,
kill-recovery/resurrection, gate re-ordering for pass-rate, optimising judged novelty.
Those are the "cheating" class. The moat's job is to stay hard; this programme's job is to
send it better ideas.
