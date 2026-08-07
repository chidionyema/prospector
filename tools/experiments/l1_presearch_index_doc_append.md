### L1 — L1: temporal-holdout replay over store/_cache/ — how often could a lexical index over ALREADY-RETRIEVED passages have served a query before the provider was called? Zero LLM calls, zero network. Bar: §13's 20% vs exact-key 0.12%.

_Run 2026-08-07T22:17:45+00:00 · `l1_presearch_index.py` · registered docs/COMMERCIAL_READINESS_PROGRAM.md §26.7, §28.4 (L1), §13 (the 20% bar)_

- **verdict**: DO NOT BUILD
- **strict_hit_at_kmax**: 0.1191
- **k_max**: 5
- **bar**: 0.2
- **exact_key_repeat_rate**: 0.0001
- **prior_28_4_query_level**: 0.0012
- **entries**: 16,167

Receipt: `tools/experiments/l1_presearch_index_receipts.json` — reproduce with `.venv/bin/python tools/experiments/runner.py run L1`
