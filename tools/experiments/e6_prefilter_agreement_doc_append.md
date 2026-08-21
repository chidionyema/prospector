### E6 — E6: prescreen-prefilter agreement vs the LLM. Bar: >=20% call reduction at no PASS loss. Reads store/prescreen_shadow/, excludes fixture rows.

_Run 2026-08-07T21:19:39+00:00 · `e6_prefilter_agreement.py` · registered docs/COMMERCIAL_READINESS_PROGRAM.md §3 (row E6), §22_

- **decision**: KILL
- **llm_reject_rate**: 0.0472
- **llm_decisions_measured**: 975
- **max_call_reduction_at_zero_false_drops**: 0.0472
- **bar**: 0.2
- **bar_reachable_at_ci_upper**: 0
- **usable_shadow_rows**: 15
- **fixture_rows_excluded**: 0
- **observed_call_reduction**: 0
- **observed_false_drops**: 0

**Verdict:** {'observed_meets_bar': False, 'any_threshold_meets_bar': False, 'sample_large_enough_to_rule_on_observed': False, 'min_rows_to_rule': 100, 'killed_on_arithmetic_ceiling': True, 'decision': 'KILL'}

Receipt: `tools/experiments/e6_prefilter_agreement_receipts.json` — reproduce with `.venv/bin/python tools/experiments/runner.py run E6`

**Follow-through:** NO ACTION — the report's own verdict is KILL on the arithmetic ceiling: no threshold meets the bar, so there is no version of this change worth making.
