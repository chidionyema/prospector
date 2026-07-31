# Catalogue factory fix — yield without softening the moat

Date: 2026-07-30. Branch: `discovery-ux-2026-07-30`.

## Goal

Steady **PASS → listing** for sellable UK packs. Moat bars untouched
(`hard_gates` / thresholds / weights / readiness bars unchanged).

## Catalogue preset (default path)

| Knob | Catalogue default | Notes |
|------|-------------------|--------|
| k | ≤5 (CC slider max 5) | Was grinding multi-lane k=20 |
| lane | `side_hustle` | Empty = MIX multi-lane (explicit, last in picker) |
| profile | `statutory_compliance_pack` | Generation-only; never a gate |
| archetype | `solo_agent` (lane default) | |
| publish | ON | Artifacts + EngineBridge + local listing receipt |
| market | `uk` (open) | US stays closed until READY |

**Multi-lane MIX is a separate research job**, not the catalogue default.
CC Launch warns when MIX is selected; k remains capped at 5.

CLI equivalent:

```bash
.venv/bin/python -m prospector.run generate \
  --candidates 5 --lane side_hustle --market uk \
  --archetype solo_agent --profile statutory_compliance_pack --publish
```

Concurrency: `retrieval.vet_workers: 2` + `PROSPECTOR_CURSOR_CONCURRENCY=2`
(set in `tools/queue_yield_batch.sh` / operator shell).

## What shipped

### Phase 1 — Listings integrity
- Local `store/listings/<id>.json` receipt on EngineBridge success (CC Pub=Y).
- `tools/backfill_missing_listings.sh` — all non-provisional PASSes missing listings.
- CC Overview KPIs: sellable PASS / provisional PASS / listed (plus KILL/spend).
- Catalogue Launch defaults: side_hustle + statutory pack + publish ON.

### Phase 2 — Stop the grind
- CC generate k capped at 5; MIX called out as non-default.
- k=20 job cancelled; focused k=5 catalogue job is the yield path.
- `tools/queue_yield_batch.sh` documents catalogue preset + cursor concurrency.

### Phase 3 — Throughput (no bar change)
- Soft early-exit in `verify.py` via `pass_ceiling.pass_impossible_reason`:
  skip remaining *soft* checks / adversarial only when PASS cannot meet
  `min_supported` / `moat_critical` / theoretical max composite.
  DEFER-safe: never soft-kill on `retrieval_failed`; never skip remaining
  hard gates. Instrumentation: `checks_run` / `checks_skipped_soft_exit`
  (log + audit + `cand.tags.verify_throughput`).
- Concurrency aligned: `vet_workers` / `cursor_concurrency` /
  `claude_concurrency` (=2) + `PROSPECTOR_CURSOR_CONCURRENCY`.
- Query-gen / CLI caps: `query_gen_timeout=90` (no retry burn);
  `cli_timeout=120` / `cli_timeout_max=180` for completion brains.
- `min_composite` still pays full price under normal bars (score is
  post-suite; only a theoretical-max-below-bar misconfig soft-exits).
- Tests: `tests/unit/test_pass_ceiling.py`,
  `tests/unit/test_soft_early_exit_verify.py`,
  `tests/unit/test_cli_timeout_concurrency.py`.

### Phase 4 — Pack completeness (Epic C lite)
- `pack_floors.py`: claim-safe listing / exec summary / first-week checklist
  from dossier fields only (no invented numbers).
- Bridge zips those floors; marketing stub header alone is gone.
- `validate_pack` still refuses to LIST incomplete artifacts.

### Phase 5 — US readiness
- Calibration + exemplars already side_hustle / regulator-named.
- Probe with `--lane side_hustle`; open US **only** if READY.
- If NOT READY: leave `markets.us.status: closed` and record gap in checkpoint.

## Operator commands

```bash
# Backfill listings (durable)
nohup bash tools/backfill_missing_listings.sh &

# Yield waiter (after a blocking job id)
TARGET_JOB=... nohup bash tools/queue_yield_batch.sh \
  >> store/control_center/runs/queue_yield_batch.log 2>&1 &

# US probe (does not open the market by itself)
.venv/bin/python -m prospector.run markets probe \
  --market us --set markets/calibration/us.jsonl --lane side_hustle
# Only if READY:
.venv/bin/python -m prospector.run markets open --market us
```
