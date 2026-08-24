### E6B — E6B — replays the shipped lexical prefilter over the dossier corpus labelled by FINAL outcome, and reports the largest share of prescreen calls it could have removed while losing no PASS.

_Run 2026-08-08T01:24:56+00:00 · `e6b_prefilter_pass_safety.py` · registered docs/COMMERCIAL_READINESS_PROGRAM.md §3 (row E6), §22, §32_

**Verdict:** FAILS_BAR

Receipt: `tools/experiments/e6b_prefilter_pass_safety_receipts.json` — reproduce with `.venv/bin/python tools/experiments/runner.py run E6B`

**Follow-through:** NO ACTION — the report's own verdict is FAILS_BAR. The prefilter cannot be shown safe on passes, so it stays off.
