### E18 — E18 — tests whether packaging-vocabulary-leading queries retrieve worse, correcting for the fact that the vocabulary is a property of the CANDIDATE

_Run 2026-08-08T01:00:33+00:00 · `e18_query_vocabulary_confound.py`_

- **verdict**: DO_NOT_ACT
- **why**: the naive association does not survive adjustment — the adjusted intervals span zero, and the point estimates do not even carry the naive sign. Editing the query builder on the naive number would be a blind change of unknown sign.
- **wrapper_prevalence**: 0.2303
- **n_checks**: 7,843

Receipt: `tools/experiments/e18_query_vocabulary_confound_receipts.json` — reproduce with `.venv/bin/python tools/experiments/runner.py run E18`

**Follow-through:** NO ACTION — the report's own verdict is DO_NOT_ACT: the naive association does not survive adjustment and the point estimates do not carry the naive sign. Editing the query builder here would be a blind change of unknown sign.
