### E15 — HHEM groundedness audit of the live catalogue + rationale-infidelity rate

_Run 2026-08-07T20:23:26+00:00 · `e15_hhem_groundedness.py` · registered docs/COMMERCIAL_READINESS_PROGRAM.md §14 (line ~504)_

- **eligible ruled checks with a resolvable cited passage**: 2,649
- **sampled and scored**: 350
- **HHEM pairs (cited + uncited + null controls)**: 1,221
- **calibrated threshold tau (95th pct of NULL control)**: 0.0691
- **median HHEM score, CITED passage**: 0.0713
- **median HHEM score, NULL control**: 0.0148
- **rationale-infidelity rate**: 171/350 = 48.9% (95% CI 43.7%-54.1%)

**Verdict:** measured rationale-infidelity rate 48.9% (171/350, 95% CI 43.7%-54.1%) at tau=0.0691, calibrated so 95% of unrelated pairs fall below it

Population / selection rule: ruled checks (supported|refuted) holding >=1 citation that resolves to a stored passage with text: 2649 eligible; sampled 350 by: systematic every-k-th within each verdict class, k = class_size/quota, quota proportional to the class mix; deterministic, no RNG (limit=350)

Limitations:
- tau is calibrated PER RUN on that run's own NULL sample, and the dossier store is live, so the headline rate is stable to about +/-5pp, not to the decimal. Measured directly 2026-08-07: two runs 40 min apart over the same 2649-eligible population drew different 350-check samples (16 dossiers were rewritten in between) and gave tau 0.0589 -> 43.4% and tau 0.0691 -> 48.9%. Both runs agree the rate is near half; neither pins it finer. `corpus_fingerprint` in these receipts is what distinguishes a genuine repeat from a fresh sample. Discrimination was stable across both (+0.1230, +0.1253).
- The UNCITED control arm is EMPTY and cannot be filled from this corpus: of 6073 checks that cite anything, 6073 cite EVERY passage they retrieved and 0 leave one out. `cited` therefore means RETRIEVED-FOR-THIS-CHECK; this experiment cannot test whether the model picked the RIGHT passage, only whether the passages it had entail what it wrote.
- HHEM measures ENTAILMENT of the rationale by the cited passage, not truth. A true statement recalled from pretraining rather than read in the passage scores low — which is the intended finding under verdict-from-retrieval-only, not a false positive.
- `refuted` rationales contain negation, which entailment models handle worse than affirmations. The by-verdict breakdown is published so that confound is visible rather than averaged away; E17 tests it directly.
- Premise = each cited passage separately (max taken), capped at 1500 chars and 3 passages. Longer evidence is truncated by HHEM's 512-token window; concatenating instead would truncate MORE and bias the rate upward.
- tau is calibrated on the NULL control, not on human labels. No human has labelled any pair here, so the absolute rate is only as good as that calibration; the sweep is published so a different tau can be read off directly.
- store/dossiers is written by the live daemon; _meta.run_at_utc pins the corpus.

Receipt: `tools/experiments/e15_hhem_groundedness_receipts.json` — reproduce with `.venv/bin/python tools/experiments/runner.py run E15 --limit 350`
