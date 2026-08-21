### E2 — E2 baseline: PASS rate and grounding by audience persona, with intervals and the batch size the live arm needs (offline, zero spend)

_Run 2026-08-08T00:38:31+00:00 · `e2_persona_grounding.py` · registered COMMERCIAL_READINESS_PROGRAM.md §4 (table), §8 (baseline)_

- **dossiers**: 1,611
- **tagged_with_decision**: 1,574
- **personas_seen**: 12
- **personas_in_config**: 13
- **spread_verdict**: {'tested': True, 'best': 'gen_z_worker', 'worst': 'freelancer_creative', 'ratio': 12.87, 'separable': True, 'best_ci': [0.05, 0.1175], 'worst_ci': [0.0011, 0.0329]}
- **class_pass_rate**: {'business': 0.0646, 'household': 0.0469}
- **class_separable**: 0
- **live_arm_n_per_arm**: 2,637
- **power**: 0.8
- **v1_operator_dossiers**: 16
- **baseline_covers_v1_arm**: 0
- **personas_with_zero_dossiers**: ecommerce_seller

Receipt: `tools/experiments/e2_persona_grounding_receipts.json` — reproduce with `.venv/bin/python tools/experiments/runner.py run E2`

**Follow-through:** TICKET #565 — ecommerce_seller is configured and has produced zero dossiers, and the 12.87x pass-rate spread is confounded with the signals each persona draws, so re-weighting on it now would repeat the mistake E18 ruled against.
