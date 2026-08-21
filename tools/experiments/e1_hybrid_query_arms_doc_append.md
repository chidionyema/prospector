### E1 — E1: paired A/B of entity-template vs LLM query generation on the three worst-grounded checks, fenced so an arm that never engaged aborts instead of reading as 'no effect'.

_Run 2026-08-07T23:26:35+00:00 · `e1_hybrid_query_arms.py` · registered docs/COMMERCIAL_READINESS_PROGRAM.md §3 (row E1), §18.3 'What this changes about E1', §18.4 'A limit on E1's measurement plan'_

- **mode**: live
- **checks**: payer_solvency, incumbency, legality
- **paired_candidates**: 8
- **templates_present**: incumbency, legality, payer_solvency
- **arm_engages_offline**: 1
- **planned_check_runs**: 48
- **live_path**: {'operator': 'claude-cli/default', 'search': 'DiskCache', 'ruling_providers': 'claude_cli'}
- **separable_checks**: 
- **deltas**: {'payer_solvency': 0.3036, 'incumbency': 0.25, 'legality': 0.7083}

Receipt: `tools/experiments/e1_hybrid_query_arms_receipts.json` — reproduce with `.venv/bin/python tools/experiments/runner.py run E1 --live --verbose`

**Follow-through:** NO ACTION — separable_checks is EMPTY, so no arm separated and the design as built cannot rule. Re-running it unchanged would produce the same non-result at live-call cost.
