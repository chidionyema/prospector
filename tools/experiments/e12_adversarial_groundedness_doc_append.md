### E12 — adversarial groundedness — do decisive kills cite a passage we hold?

_Run 2026-08-07T20:23:50+00:00 · `e12_adversarial_groundedness.py` · registered docs/COMMERCIAL_READINESS_PROGRAM.md §9 (line ~323)_

- **adversarial_decisive kills audited (json)**: 142
- **same, per store/prospector.db**: 156
- **cited — every id resolves to a passage with text**: 120
- **partial — some ids resolve**: 0
- **dangling — NO id resolves (invented receipts)**: 8
- **uncited — empty citations (pure opinion)**: 14
- **unparseable**: 0
- **points at a passage we hold**: 120/142 = 84.5% (95% CI 77.7%–89.5%)
- **dangling citation ids / all citation ids**: 16/401 = 4.0%
- **era of the ungrounded kills vs the whole population**: 2026-06-15..2026-06-16 within 2026-06-15..2026-06-24

**Verdict:** 22 of 142 adversarial_decisive kills (15.5%) rest on NO passage we hold. Every one of them falls in 2026-06-15..2026-06-16, inside a population spanning 2026-06-15..2026-06-24 — so this is a PRE-GUARD artefact, not a live defect: `verify.py:672-674` now downgrades decisive-with-no-citations, and the `dangling` class (an id that resolves to nothing) is the hole that guard still does not close.

Population / selection rule: every dossier json with gate_fired == 'adversarial_decisive' (142 of 1597 parsed dossiers); no sampling, the whole population is audited

Limitations:
- Resolution is POINTING, not support. A citation that resolves proves we hold the passage, not that the passage carries the kill case. E15 scores exactly these kill_case/passage pairs with HHEM; read the two together.
- `verify.py:672-674` already blocks decisive-with-zero-citations, so the `uncited` count is expected near zero. `dangling` is the class that guard does not catch.
- The json glob and the sqlite index disagree on the population size by design (the index outlives rotated json files); both counts are reported, neither is preferred.
- store/dossiers is written by the live daemon, so a later re-run shifts counts by a few dossiers. _meta.run_at_utc and dossier_files_globbed pin this run.

Receipt: `tools/experiments/e12_adversarial_groundedness_receipts.json` — reproduce with `.venv/bin/python tools/experiments/runner.py run E12`
