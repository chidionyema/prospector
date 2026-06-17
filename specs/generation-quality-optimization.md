# Spec: Generation Quality Optimization — Positive Learning Loop + Robust DPP

## Goal
Genuinely increase PASS rate by giving the generation pipeline a working
positive-feedback loop and fixing the broken DPP diversity selection. The moat's
gates and thresholds do NOT change — this is pure generation-side improvement.

## Root causes identified
1. `select_diverse_candidates` calls `op.embed()` which returns `[]` on all
   operators except `GeminiOperator`. DPP is a no-op — candidates selected by
   prescreen score alone, zero diversity forcing.
2. `get_exemplars` in adaptive.py feeds back KILLs but never analyzes PASS
   survivors for common traits (sector, form, audience, wedge type).
3. `generate_system.md` has hardcoded "GOLDEN PASS PATTERNS" that never update.
4. Grid scheduler only targets zero-count cells — never boosts fertile ones.

## Changes

### 1. Text-based diversity fallback in `novelty.py`
When `op.embed(text)` returns empty list (all non-Gemini operators), fall back
to a text-based similarity measure:
- Extract all words (3+ chars, lowercase) from title + one_liner
- Jaccard similarity = |A ∩ B| / |A ∪ B|
- Use this as the `cosine_similarity` stand-in
- This is deterministic, zero-cost, and actually forces diversity

### 2. Positive trait extraction from PASSes in `adaptive.py`
New function `get_pass_traits(store, n=20) -> str`:
- Load recent PASS dossiers
- Extract: sectors, structural forms, audience personas, durable wedge types
- Compute frequency distribution
- Return a compact summary string injected as `pass_patterns` into generation

### 3. Dynamic golden patterns via prompt variable
New template variable `{pass_patterns}` in `generate.md` / `generate_system.md`.
When PASSes exist, this overrides the hardcoded patterns with actual survivors.
When no PASSes exist, falls back to existing hardcoded patterns.

### 4. Fertile-cell boosting in grid scheduler (`calculate_grid_priorities`)
Instead of only targeting zero-count cells, also compute per-cell PASS rate and
boost cells with high PASS rates (add them to the priority list multiple times
so they get more generation budget).

### 5. Exclude refinement for structurally-thin candidates
Skip LLM refinement call for candidates whose title + one_liner is under 50 chars
(these are thin and the moat will kill them anyway — don't spend refinement budget).
Add a `_refine_wave` filter that only refines candidates with substantive text.

## Files to touch
- `prospector/novelty.py` — add `_text_similarity()` fallback in `select_diverse_candidates`
- `prospector/adaptive.py` — add `get_pass_traits()`, fix `get_exemplars()`, improve `calculate_grid_priorities()`
- `prospector/generate.py` — add refinement skip for thin candidates, pass `pass_patterns` to prompts
- `prompts/generate_system.md` — add `{pass_patterns}` template variable
- `prompts/refine_system.md` — no change needed (uses lane_directive only)

## Acceptance criteria
- `pytest tests/unit/ -q` still green (no regression)
- `pytest tests/behavioural/ -q` still green
- New tests for text similarity, pass trait extraction, fertile-cell boosting
