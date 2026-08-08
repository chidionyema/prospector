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
| G7 | Coverage sampler V2 yield-weighting | `coverage.py` new method `yield`: cell deficit weighted by measured PASS-yield of the cell value (fertile-and-underfed first) with an exploration floor for never-tried values. Enable the sampler (`coverage_sampler.enabled: true`, method `yield`). | specified |
| G8 | Critique->revise single pass | 2-3 parallel critiques -> ONE revision call, index-mapped (never title-matched), strictly non-lossy (identity fallback keeps every candidate). Replaces the retired refine-wave. Gate: `generation.critique_revise.enabled`. Never drops or kills a candidate — it only rewrites weak wedges/differentiation in place. | specified |
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

## What is deliberately NOT here

Anything that moves the verification bar: confidence-floor changes, claim reframing,
kill-recovery/resurrection, gate re-ordering for pass-rate, optimising judged novelty.
Those are the "cheating" class. The moat's job is to stay hard; this programme's job is to
send it better ideas.
