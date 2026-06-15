# SPEC: Multi-lane-by-default mixed catalogue

**Author:** Claude (design) → **Implementer:** Gemini CLI
**Status:** ready to implement
**Date:** 2026-06-15

## 0. Context (read first)
Prospector generates business-opportunity assets that are SOLD to buyers spanning a full
ambition spectrum — from people seeking a side hustle to people wanting to launch a startup.
The product is therefore a **mixed-ambition catalogue**, not a single tier.

Today the engine runs ONE ambition lane per run via a `--lane` CLI flag (mono-ambition). This
spec makes **multi-lane the DEFAULT**: a single run produces a catalogue spanning all tiers,
each idea judged by the bar of its OWN tier.

### TWO ORTHOGONAL AXES — do not conflate (this is the core correction)
1. **Ambition tier (a.k.a. lane):** the SCALE/bar of the *opportunity* — `side_hustle`,
   `smb`, `growth`, `venture`. Controls the vetting gates/thresholds/weights, the adversarial
   framing, and the kind of opportunity generated.
2. **Asset packaging:** how we PACKAGE and SELL the opportunity to the buyer (a "pack" =
   blueprint + go-to-market plan + build/launch kit, priced per tier). This is DOWNSTREAM and
   applies to EVERY tier. It is NOT part of a lane's idea space.

**BUG TO FIX:** `config.yaml` currently bakes the asset packaging ("£30 INFO-PRODUCT PACK",
pack-only `structural_forms`) into the `side_hustle` LANE's generation. Decouple: the
`side_hustle` lane must generate diverse side-hustle-SCALE *opportunities*, not "£30 packs".

## 1. Hard guardrails (DO NOT VIOLATE)
- **Grounded core is untouchable.** Do NOT change retrieval/grounding semantics, source-or-die,
  kill-fast, the verdict polarity rules in `prompts/verdict.md`, or the adversarial grounding.
- **Golden set must stay green** (`pytest tests/ -k golden`) and **full suite green**
  (`pytest tests/` — currently 173 passed). Run both after each change.
- **Venture/default behaviour byte-for-byte unchanged** when multi-lane is not engaged
  (i.e. a single-lane run or `active_lanes: [venture]` must behave exactly as today).
- No hardcoded values in code — all tiers/quotas/forms live in `config.yaml`.
- Keep the existing `--lane` flag working as an OPTIONAL single-tier filter.

## 2. Data model changes — `prospector/models.py`
- Add field to `Candidate`: `ambition_tier: str = ""`.
- Propagate `ambition_tier` into `Dossier` (and its `to_dict()`), so every catalogue entry is
  tagged by tier. Default "" (back-compat).
- No other contract changes.

## 3. Config — `config.yaml`
### 3a. New multi-lane default set
Add top-level:
```yaml
active_lanes: [side_hustle, smb, growth, venture]   # multi-lane default; one run spans all
lane_quota:                                          # candidates generated per tier per run
  side_hustle: 4
  smb: 3
  growth: 3
  venture: 3
```
Keep existing `active_lane: ""` (single-lane override; empty = use active_lanes).

### 3b. Decouple side_hustle from "£30 pack" (THE FIX)
Replace `lanes.side_hustle.generation` so it describes side-hustle-SCALE OPPORTUNITIES in
diverse forms, NOT downloadable packs:
```yaml
    generation:
      lane_directive: >
        LANE OVERRIDE — ignore every durable-moat/wedge/defensibility requirement below; it
        does not apply. Generate SIDE-HUSTLE-SCALE OPPORTUNITIES: things one solo person can
        start with little capital for supplemental or replacement income. Judge ONLY on
        DEMAND (people actively searching/paying now), DELIVERABILITY (a beginner can follow
        an open route to the outcome), and CURRENCY (live now). Commoditised/crowded niches
        are GOOD (crowds = buyers). Span DIVERSE forms — do NOT collapse to one format.
        Name a SPECIFIC opportunity, not a platform/marketplace/registry/venture.
      structural_forms:
        - local_service            # a hands-on local service one person can deliver
        - micro_ecommerce          # a small niche product store (POD, dropship, handmade)
        - productized_freelance    # a freelance skill sold as a fixed-scope product
        - content_channel          # a monetised audience in a specific niche
        - niche_micro_saas         # a tiny single-workflow tool for one niche
        - marketplace_seller       # selling into an existing marketplace's demand
        - rental_arbitrage         # renting/reselling an asset or access
        - info_product             # a course/templates/kit teaching a valuable skill
```
(The "£30 pack" is now ONLY the selling format applied downstream — see §6 — not the idea space.)

### 3c. Add smb and growth lanes
Add `lanes.smb` and `lanes.growth` between `side_hustle` and `venture`. Each MUST include
`hard_gates`, `thresholds`, `weights` (may inherit defaults), `adversarial_directive`, and a
`generation` block (lane_directive + structural_forms). Bars escalate side_hustle → venture:
- **smb:** a small business (1–20 staff) that throws off real owner income. Gates add
  `payer_solvency` + `distribution` as HARD; `min_composite_to_pass` ~2.6; adversarial_directive
  allows commoditisation but kills on unit-economics/no-real-business failure.
- **growth:** a venture-track business that must show a repeatable growth motion but not yet a
  deep moat. Gates add `pain_reality` hard; `min_composite_to_pass` ~2.9; adversarial kills on
  no-scalable-channel / no-retention.
- **venture:** UNCHANGED (existing default six-gate moat lane). Do not touch.
Use the existing `for_lane()` merge semantics (hard_gates replace; thresholds/weights/generation
merge over defaults). Mirror the structure of the existing `side_hustle` lane.

## 4. Auto-classify step — new `prospector/classify.py`
- `classify_tier(op, cand, cfg) -> str`: one cheap LLM call (use the fast/query model, NOT the
  verdict model) that reads the candidate and returns exactly one of `cfg.active_lanes`.
- New prompt `prompts/classify.md` (SYSTEM/USER, same format as other prompts) instructing the
  model to assign the ambition tier by the SCALE of the opportunity (income side-gig → small
  business → growth startup → venture). Output strict JSON: `{"tier":"side_hustle|smb|growth|venture","rationale":"<=1 sentence"}`.
- Deterministic fallback: on parse failure or unknown tier, keep the tier the candidate was
  generated under (never crash, never silently drop).

## 5. Run orchestration — `prospector/run.py` + `prospector/generate.py`
### 5a. Multi-lane generation (fan-out for coverage)
- New helper (in run.py or generate.py): `generate_multilane(op, cfg, ...) -> list[Candidate]`.
  For each tier in `cfg.active_lanes`: build `lane_cfg = cfg.for_lane(tier)`, call existing
  `generate(op, lane_cfg, k=cfg.lane_quota[tier], ...)`, and set `cand.ambition_tier = tier`
  on each result. Concatenate across tiers → mixed candidate list.
- The existing single-lane path (when `--lane X` is passed, or `active_lane` set) stays:
  generate only that tier.
### 5b. Classify-to-confirm (the bar fits the idea — "both")
- After generation, for each candidate call `classify_tier(...)`. If the classified tier
  differs from the generated tier, RE-ASSIGN `cand.ambition_tier` to the classified tier (the
  vetting bar must match what the idea actually IS).
### 5c. Per-tier vetting
- When vetting each candidate, resolve config to ITS tier: `vet_cfg = cfg.for_lane(cand.ambition_tier)`
  and pass `vet_cfg` into the existing `verify()` / `vet_candidate()` path. (Vetting is already
  lane-aware; just feed it the per-candidate lane-resolved cfg.)
### 5d. Wiring
- The DEFAULT `generate` / `signal` / `discover` runs (no `--lane`) use the multi-lane path.
- `--lane X` forces single-tier (existing behaviour) and skips classify (tier is pinned).

## 6. Catalogue / publish — `store.py` + `publish.py`
- Persist `ambition_tier` on each stored dossier/listing.
- Listing JSON must carry `ambition_tier` so the storefront can filter (side hustle vs startup).
- Pricing: keep existing `listing.pricing`; packaging (£30 pack) is unchanged and applies to
  all tiers — no change needed beyond carrying the tier tag.

## 7. Tests
- Keep full suite + golden green.
- Add `tests/unit/test_multilane.py`:
  - `for_lane('smb')` / `for_lane('growth')` resolve gates/thresholds/generation correctly and
    do not mutate the base config.
  - multi-lane generation tags each candidate with a tier and respects `lane_quota` (use Mock
    operator / FixtureProvider — NO live calls).
  - classify fallback keeps the generated tier on parse failure.
  - a candidate generated as `venture` but classified `side_hustle` is vetted with the
    side_hustle bar (assert `cfg.for_lane('side_hustle')` is what reaches verify).
- Add per-lane golden discrimination later (out of scope here; note as TODO).

## 8. Acceptance criteria (Definition of Done)
1. `python -m prospector.run generate --candidates 12` (NO --lane) produces candidates with a
   MIX of `ambition_tier` values spanning at least 3 tiers, each vetted against its own bar.
2. `python -m prospector.run generate --lane venture` behaves exactly as today (single tier).
3. `pytest tests/` green (>=173 + new tests); `pytest tests/ -k golden` green.
4. No hardcoded tiers/quotas/forms in code — all in config.yaml.
5. side_hustle generation no longer references "£30 pack"; it generates diverse side-hustle
   opportunities. The £30-pack packaging still applies downstream across all tiers.
6. Each catalogue/listing entry carries `ambition_tier`.

## 9. Out of scope (do NOT do)
- Changing grounding/verdict/adversarial semantics.
- Touching the venture lane's gates.
- Storefront UI. Per-lane golden fixtures (separate task).
