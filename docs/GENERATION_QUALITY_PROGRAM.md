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

| id | item | mechanism | status |
|----|------|-----------|--------|
| G1 | Distinct-k diversity meter | `prospector/diversity.py`: per-batch distinct-k (greedy clustering on dedup's content-token Jaccard, threshold 0.34), mean/max pairwise overlap, per-axis entropy (form/audience/market/tier). Receipts appended to `<store_dir>/generation_metrics.jsonl` at stages `generated` and `post_dedup`. Gate: `generation.diversity_meter`. | built |
| G2 | Incumbent-landscape seed enrichment | `prospector/landscape.py`: ONE bounded retrieval per signal -> "ALREADY BUILT — differentiate" block (top domains + titles) injected into the generate prompt. Fails open to empty. Gate: `generation.landscape.enabled`. | built |
| G3 | Kill-family denial constraints | `prospector/denylist.py`: mine the FULL kill corpus (not a 20-row window) into standing exhausted families (>=3 kills on `value_durability`/`incumbency`/`adversarial`, clustered by content-token Jaccard). Cached in `<store_dir>/exhausted_families.json`, refreshed when kills grow by 25. Appended to failure modes. Decay-proof: the window forgets, the denylist does not. Gate: `generation.denylist.enabled`. | built |
| G4 | Persona widening + Verbalized Sampling | Descriptions for the 5 undescribed business personas (they currently render as bare slugs, `generate.py` `_AUDIENCE_DESCRIPTIONS`); VS instruction ("enumerate the obvious 5, discard, output the tail") in the output contract. Gate: `generation.verbalized_sampling`. Differentiate-rewrite is folded into G8's revision machinery. | built |
| G5 | Seed provenance + survival analysis | Stamp `tags.seed_kind` (signal / blue_sky / archetype) at generation; `tools/generation_survival.py` reports survival by seed_kind x persona x form from the store. Zero-LLM. | built |
| G7 | Coverage sampler V2 yield-weighting | `coverage.py` new method `yield`: cell deficit weighted by measured PASS-yield of the cell value (fertile-and-underfed first) with an exploration floor for never-tried values. Enable the sampler (`coverage_sampler.enabled: true`, method `yield`). | built |
| G8 | Critique->revise single pass | 2-3 parallel critiques -> ONE revision call, index-mapped (never title-matched), strictly non-lossy (identity fallback keeps every candidate). Replaces the retired refine-wave. Gate: `generation.critique_revise.enabled`. Never drops or kills a candidate — it only rewrites weak wedges/differentiation in place. | built |
| G9 | Measured lane quotas | `run.py` `_lane_counts` mode `measured`: lane weights from smoothed store yield (PASS-rate x composite) with a 20% uniform exploration reserve, floor 1/lane. Gate: `generation.lane_quota_mode` (`static` default). | built |

## Status ledger

- 2026-08-08: branch created off main + merged `fix/kill-log-smoke-selectors`,
  `fix/live-smoke-checks-log-selectors` (both verified clean with `git merge-tree`).
  Spec written. Implementation dispatched in chunks (A: G1+G3+G4-personas,
  B: G2+G4-VS, C: G5+G9, D: G7+G8), each verified with pi_gate + pytest before commit.

## What is deliberately NOT here

Anything that moves the verification bar: confidence-floor changes, claim reframing,
kill-recovery/resurrection, gate re-ordering for pass-rate, optimising judged novelty.
Those are the "cheating" class. The moat's job is to stay hard; this programme's job is to
send it better ideas.
