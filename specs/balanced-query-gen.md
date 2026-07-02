# Spec: Balanced Query Generation for Fair Verdicts

## Problem

`prompts/query_gen.md` instructs the LLM to generate ONLY disconfirming queries:

```
You write web search queries that would EXPOSE a business idea as dead.
Write 1-3 queries most likely to surface DISCONFIRMING evidence
```

This creates systematic `unverifiable` bias (92.9% observed in production):

1. Disconfirming queries search for evidence AGAINST the idea
2. When no strong disconfirming evidence is found, passages don't directly
   support the claim either — they're answering the wrong question
3. The verdict model, told to "Rule ONLY from passages" and "NEVER supported
   without a passage that directly supports it", defaults to `unverifiable`
4. Good ideas with real market evidence get squeezed into `unverifiable`
   because the evidence was gathered with the wrong question

## Fix

Rewrite `prompts/query_gen.md` to generate **balanced** queries per
`queries_per_check` (currently 2):

- 1 **confirmation query** — search for evidence the claim IS TRUE
  (existing products, market demand, regulatory support, paying customers)
- 1 **refutation query** — search for evidence the claim IS FALSE
  (named competitors, reforms that removed need, market collapse)

This gives the verdict model passages that can support EITHER outcome,
eliminating the structural bias toward `unverifiable`.

## Implementation

One file: `prompts/query_gen.md` — replace the prompt text.

One file: `tests/test_golden_set.py` — update `_make_golden_router()` query-gen
match condition if the new prompt wording changes the matched substrings.

## Acceptance criteria

1. `pytest -k golden` passes (MockOperator regression gate)
2. `pytest tests/ --ignore=tests/control_center -q` passes
3. Live diagnostic: run a real candidate through the full pipeline, observe
   supported verdicts beyond just pain_reality
4. Audit log shows both confirmatory and disconfirmatory queries generated

## Non-goals

- Changing the verdict prompt (verdict.md) — stays as-is
- Changing `queries_per_check` in config.yaml — stays as-is
- Changing any code outside prompts/ and test golden set
