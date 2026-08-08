### E17 — HHEM agreement with moat verdicts per class (E14 ladder, first rung)

_Run 2026-08-07T20:35:33+00:00 · `e17_hhem_moat_agreement.py` · registered docs/COMMERCIAL_READINESS_PROGRAM.md §14 (line ~507)_

- **eligible checks (all 3 verdict classes, >=1 stored passage)**: 7,241
- **sampled and scored**: 600
- **register's ruled-check count (claimed) vs measured eligible**: 2,458 claimed; measured eligible here 7241
- **calibrated tau**: 0.0591
- **AUC ruled vs unverifiable (threshold-free)**: 0.673
- **agreement — supported**: 96/182 = 52.8%
- **agreement — refuted**: 27/38 = 71.0%
- **agreement — unverifiable**: 257/380 = 67.6%
- **MiniCheck**: SKIPPED — no local copy; no model was downloaded

**Verdict:** HHEM separates the moat's ruled checks from its unverifiable ones with AUC 0.673; agreement at tau=0.0591 is supported 52.8% (n=182), refuted 71.0% (n=38), unverifiable 67.6% (n=380)

Population / selection rule: every check with a rationale and >=1 stored passage across ('supported', 'refuted', 'unverifiable'): 7241 eligible; sampled 600 by: systematic every-k-th within each verdict class, quota proportional to the class mix; deterministic, no RNG (limit=600)

Limitations:
- The dossier store is live and tau is calibrated per run, so a re-run with a different `corpus_fingerprint` is a fresh sample, not a repeat. E15 measured that sensitivity directly: two runs 40 min apart moved tau 0.0589 -> 0.0691 and its headline rate 43.4% -> 48.9% on the same eligible population.
- Agreement depends on the number->label mapping stated in the module docstring. The AUC is published because it is threshold-free and mapping-free, and it is the number to quote if only one is quoted.
- `refuted` rationales are negations and entailment models score negation lower. The supported/refuted split is never collapsed into one 'ruled' number without it.
- `unverifiable` checks rarely cite anything, so their premise is the passages the check RETRIEVED. premise_source_counts reports how many checks used which. A retrieved-passage premise is a weaker premise than a cited one by construction.
- Agreement is not accuracy. Neither HHEM nor the moat is ground truth here; no human has labelled any pair. This measures concordance between two instruments.
- MiniCheck was not run and not downloaded — see the `minicheck` probe for what is actually in the local HF cache.

Receipt: `tools/experiments/e17_hhem_moat_agreement_receipts.json` — reproduce with `.venv/bin/python tools/experiments/runner.py run E17 --limit 600`
