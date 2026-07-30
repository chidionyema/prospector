# Checkpoint — 2026-07-30 · Multi-market + house voice leftovers closed

## Active task
Branch `multi-market-dimension-2026-07-30` (cut from `launch-hardening-2026-06-18`).

**Status: Epic D (multi-market) + Monzo-style house-voice leftovers are DONE.**
Branch is not committed. Do not start the next task in this context.

## Verification (observed this session)
| Gate | Result |
|---|---|
| `tests/invariants/test_house_voice.py` + market retrieval + market CLI | **32 passed** |
| `.venv/bin/python -m pytest tests/ -k golden -q` | **14 passed**, 610 deselected |
| `.venv/bin/python -m pytest -q` (full suite) | **621 passed, 3 skipped** |

Known flake (do not fix): `tests/control_center/test_runner.py::TestLaunchPersist::test_launch_writes_job_to_jobs_json` — did not fire this run.

## What landed on this branch (summary)

### Epic D — multi-market dimension
`market` is a config-driven dimension (jurisdiction of the OPPORTUNITY), orthogonal to
ambition lane and buyer locale. `uk` open; `us` closed until probe passes.
See `specs/multi-market-dimension.md`. Prior session closed D0–D7 + readiness gate.

### Reliability fixes (already shipped earlier this session — do not redo)
- `prospector/verify.py` — ContextVar copy in the search pool (market authority domains
  survive thread hops).
- Market guard without `--market` (closed markets still blocked when active_market is set).
- Status rewrite regex fix (scheduler/control-center status lines).

### House voice (Monzo-style dossier tone) — DONE
- `prompts/style/voice.md` + `prompts/style/rationale.md` exist; `prompts.py` auto-injects
  `style_kwargs`. Moat prompts get fenced `rationale_style` only (never buyer `style_guide`).
- Prose prompts updated: content_gen, artifacts, verdict, adversarial, generate_system,
  refine_system, score.
- `prospector/dossier.py` renderer chrome restyled (PASS/KILL gloss, check labels, etc.).
- **Leftover closed this turn:** `build_dossier` kill reasons no longer say
  `Gate '…' fired — …`. They now read
  `It failed on: Is it legal? (\`legality\`) — …` (plain label + backtick gate for audit).
  `adversarial_decisive` / `min_composite` / `moat_ungrounded` / `source_or_die` in
  `_CHECK_LABEL`. adaptive.py still strips on first `:` (comment updated).
- `tests/invariants/test_house_voice.py` asserts kill reasons never start with `Gate '`.

### Cursor operator
**Owned by another agent — status unknown here.** Do not touch `prospector/operator.py`.

## Files touched this leftover turn
- `prospector/dossier.py` — plain-English kill reasons in `build_dossier`; extra `_CHECK_LABEL`
  entries; `_GATE_PREFIX` kept only for legacy stored dossiers.
- `prospector/adaptive.py` — comment only (stripper behaviour unchanged).
- `tests/invariants/test_house_voice.py` — `test_kill_reasons_no_longer_start_with_gate_jargon`.

## Exact next steps
1. Review the branch, then commit (still uncommitted).
2. **Founder decision — backfill.** 1,287 pre-cutover dossiers carry `market=''`.
   `python -m tools.backfill_market` (dry run) → `--apply`. Requires the `.bak` to exist.
3. To open US: live `markets probe --market us --set markets/calibration/us.jsonl`, then
   `markets open --market us` if READY.
4. Cursor operator work stays with its owning agent (unknown status from this session).

## Open problems
- None failing in the suite this run.
- US calibration expected outcomes still soft (judgement, not measured) — review before
  trusting a probe result.
- Control-center launch-persist flake remains known and unfixed by design.
