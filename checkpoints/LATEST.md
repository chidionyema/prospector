# Checkpoint — 2026-07-30 · US market OPEN (prod-ready)

## Active task
**US multi-market open** — readiness READY; opened for generate/publish. Bars NOT lowered. No yield batch started.

## Done this session
1. Confirmed `store/markets/us/READINESS.json` **verdict: ready** (probe 2026-07-30T21:58:31Z).
2. Ran `.venv/bin/python -m prospector.run markets open --market us` → success.
3. `config.yaml` `markets.us.status: open` (us-tx inherits open).
4. Generate gate: `_guard_market_open` for `--market us` and `--market us-tx` → **not refused**.
5. Fingerprint fix: hashing full market block included `status`, so open immediately made show STALE. **`config_fingerprint` now excludes `status`**; READINESS restamped `994b3aa186c35d4e`; show READY + current (no STALE).
6. Tests: expect US open; `test_fingerprint_stable_across_status_flip`. `pytest -q tests/unit/test_market_readiness.py tests/unit/test_market_config.py` → **38 passed**.

### Probe metrics (bars unchanged)
| metric | measured | bar |
|---|---:|---:|
| grounding_rate | 0.73 | 0.55 |
| authority_rate | 0.53 | 0.25 |
| discrimination | 0.83 | 0.70 |
| pass_rate | 0.33 | 0.05 |

## Exact US pack yield command (bounded + publish)
Prefer `us-tx` (`require_subdivision: true` on us). Mirror UK catalogue preset:

```bash
.venv/bin/python -m prospector.run generate \
  --candidates 5 \
  --lane side_hustle \
  --market us-tx \
  --archetype solo_agent \
  --profile statutory_compliance_pack \
  --publish
```

`--market us` also accepted. Optional: Control Center `runner.launch` with the same argv.

PASS backfill without re-vet:
```bash
.venv/bin/python -m tools.publish_passes store/dossiers/<id>.pass.json
```

## Files touched
- `config.yaml` — us status open (via markets open)
- `prospector/markets.py` — fingerprint excludes status
- `store/markets/us/READINESS.json` — fingerprint restamp under status-neutral hash
- `tests/unit/test_market_readiness.py` — status-flip stability
- `tests/unit/test_market_config.py` — US open expectations; us removed from closed stubs

## Exact next step
Launch the bounded US yield command above when ready for spend. Do not re-probe unless measuring config (authority domains / bars / gates) changes.
