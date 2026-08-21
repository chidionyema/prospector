### E3 — E3: sweeps PROSPECTOR_CLAUDE_CONCURRENCY (one subprocess per level) and measures p50/max call latency, throughput and CROSS-TALK — the collision the knee is about.

_Run 2026-08-07T22:13:00+00:00 · `e3_concurrency_knee.py` · registered docs/COMMERCIAL_READINESS_PROGRAM.md §3 (row E3), §16 'E3 — the methodology, recovered'_

- **levels**: 8, 6, 4, 1
- **knee_n**: 8
- **cross_talk_calls**: 0
- **bad_calls**: 50
- **total_calls**: 132
- **daemon_quiet**: 1
- **foreign_cli_peak**: 2
- **foreign_cli_kinds**: hermes_executor
- **single_tenant**: 0
- **order_effect_material**: 1

Receipt: `tools/experiments/e3_concurrency_knee_receipts.json` — reproduce with `.venv/bin/python tools/experiments/runner.py run E3 --levels 8,6,4,1`

**Follow-through:** SHIPPED config.yaml — `minimax_concurrency` is 8, the knee this experiment measured, and the comment above it cites the 16/16-clean zero-429 receipt. No line number on purpose; grep `minimax_concurrency`.
