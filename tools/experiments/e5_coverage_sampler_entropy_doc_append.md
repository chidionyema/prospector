### E5 — E5 setup: prove the coverage sampler engages, and size the batch count its entropy lift would need (offline, zero spend, never flips the flag)

_Run 2026-08-08T00:38:35+00:00 · `e5_coverage_sampler_entropy.py` · registered COMMERCIAL_READINESS_PROGRAM.md §4 (experiment table)_

- **enabled_on_disk**: 0
- **flag_untouched**: 1
- **index_present**: 1
- **control_cells**: 0
- **treatment_engages**: 1
- **treatment_cells**: 15
- **batches_per_arm**: 3
- **k_per_batch**: 15
- **worst_axis_mde_normalised**: 0.369
- **target_mde**: 0.1
- **batches_per_arm_for_target**: 41
- **design_runnable**: 1

Receipt: `tools/experiments/e5_coverage_sampler_entropy_receipts.json` — reproduce with `.venv/bin/python tools/experiments/runner.py run E5`
