# Checkpoint — 2026-06-16 (final, session 3)

## Status: ✅ All asked-for work complete

**6 commits added on `bug3-fulfilment-chain`** (uncommitted work preserved + model-config refactor):

```
5cf941b docs: mark model-config audit step 2 partial done
1d36dd3 operator: thread cfg.model through to minimax + deepseek
5048ded Store.Api + Store.Web: provider-agnostic checkout (P4 / P7)
fc4eae6 bridge: provider-agnostic product provisioning (P3)
c27b878 docs: payment rail P0 brief + independence spec + Nina handoff
6604e60 docs: hardcoded model identifier audit ticket
61c29c2 CC runner: retention sweep for stale run logs (CC go-live #4)
8c659d1 Store: atomic dossier writes — cancel-safety (CC go-live #1)
```

## What was preserved (uncommitted → now committed)

- `tests/control_center/test_cancel_safety.py` — 3 tests for atomic write + cancel
- `prospector/store.py` — atomic write-temp-then-rename
- `prospector/control_center/runner.py` — `sweep_old_logs` (CC go-live #4)
- `tests/control_center/test_runner.py` — 3 retention tests
- `prospector/bridge.py` — `ProductProvisioner` Protocol + `StripeProvisioner` (P3)
- `tests/test_engine_bridge.py` — 9 new tests (Protocol, ProviderSelection, KnownGaps)
- `store_platform/...` — Store.Api checkout endpoint, Store.Web Stripe/Paddle routing,
  `ProviderParityTests` (P4/P6/P7), `package-lock.json` now tracked, `store.db-shm/wal` untracked
- `docs/PAYMENT_P0_GEMINI_BRIEF.md`, `docs/PAYMENT_RAIL_INDEPENDENCE_SPEC.md`,
  `docs/REMAINING_WORK_NINA_BRIEF.md` — the briefs the user authored

## What was built (model-config refactor)

- `prospector/operator.py` — `_build_operator` now threads `cfg.model` and `cfg.model_fast`
  through to all 4 non-mock operators (gemini, claude, deepseek, minimax). Empty config
  falls back to operator defaults; non-empty overrides win.
- `tests/unit/test_model_config.py` — 8 tests locking the invariant. The
  deepseek-chat 2026-07-24 deprecation is now a 1-line `config.yaml` change.
- `docs/HARDCODED_MODEL_AUDIT_TICKET.md` — updated with progress; remaining TODO is
  the per-operator `_DEFAULT_MODEL` strings (step 2 of the audit, partial).

## Verification

- `pytest -q` — **300 passed, 3 skipped** (was 277 before this session)
- `dotnet test` (Store.Tests) — **39 passed, 0 failed**
- The 3 skips are all `anthropic` SDK / `jiter` env issues, not code

## Still TODO (not in scope of this ask)

- `retrieval.py:455,599,743` — `model_name` strings for DeepSeekSearchProvider,
  MiniMaxSearchProvider, OpenRouterSearchProvider (audit step 2 partial)
- `telemetry.PRICING` — config-driven pricing (audit step 3)
- The 4 per-operator `_DEFAULT_MODEL` strings (would be eliminated by audit step 2 final)
- `tests/control_center/test_runner.py` and `tests/unit/test_model_config.py` still skip Claude
  tests due to broken `jiter` in this venv — fix the jiter install to unskip

## Carry-over

- Rotate R2 + Gemini creds that were pasted in plaintext (still in `~/.config/llm/secrets.sh`)
- `git gc` warning (loose objects) — harmless

The branch `bug3-fulfilment-chain` is now **10 commits ahead of origin** (was 4).
