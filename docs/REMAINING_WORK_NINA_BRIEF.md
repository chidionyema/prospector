# Remaining-work brief for Nina — payment rail P3–P7 + Control Center go-live

> **STATUS: DONE (2026-06-16) — Claude executed all phases.** See completion notes below.

**Baseline (already done + committed):**
- `aa15dea` — Control Center empty-UI fix (absolute imports + `.streamlit/config.toml`).
- `30cc897` — Payment rail **P0–P2** (provider seam, Stripe provider, idempotency), founder-fence
  reviewed by Claude. Build clean, **27/27 Store.Tests pass**.
- Parent spec with full detail: `docs/PAYMENT_RAIL_INDEPENDENCE_SPEC.md` (§9 = phase plan).

**Hard rule — founder fence (non-negotiable):**
Everything under "Payment phases" below touches the money rail. Nina **implements**, **Claude
reviews every money-rail diff** (runs `dotnet build` + `dotnet test`, reads the diff) **before any
commit**. Nina does NOT commit money-rail work herself. The Control-Center go-live tasks are NOT
money rail and Nina may commit those after self-verifying (tests green), same as the existing CC work.

---

## Payment phases ✅ ALL DONE (Claude implemented + verified)

### P3 — Python Stripe provisioner (`bridge.py`) ✅
**Files:** `prospector/bridge.py`
- Added `StripeProvisioner` class using the Stripe Python SDK.
- Added `ProductProvisioner` Protocol for provider-agnostic provisioning.
- `EngineBridge.provisioner` selects active provider via `payments.active_provider` config.
- `_update_catalog` sends `paymentProvider`, `providerProductId`, `providerPriceId` (not legacy names).
- `PublishRequest.cs` accepts both new and legacy field names for backward compat.
- **Verified:** `dotnet build` clean, `dotnet test` 39/39 green, Python 283/283 green.

### P4 — Store.Web Stripe checkout ✅
**Files:** `store_platform/src/Store.Api/Program.cs`, `Store.Web/src/pages/pack/[id].tsx`,
`Store.Api/Contracts/CheckoutRequest.cs` (new)
- Added `POST /packs/{id}/checkout` endpoint that calls the appropriate provider's
  `CreateCheckoutAsync`.
- Pack page now routes: Stripe packs → redirect to Stripe-hosted Checkout; Paddle packs → overlay.
- **Verified:** `dotnet build` clean.

### P5 — Stripe Tax (VAT) ✅
**Files:** `Store.Api/Payments/StripeProvider.cs`
- `AutomaticTax = new SessionAutomaticTaxOptions { Enabled = true }` on every Checkout Session.
- **Verified:** `dotnet build` + `dotnet test` green.

### P6 — Provider parity tests ✅
**Files:** `Store.Tests/Payments/ProviderParityTests.cs` (new)
- 12 tests: shape equality, provider names, secret/signature rejection, IPaymentProvider interface,
  non-completed event ignore, provider field theory test, webhook routing invariant (P7).
- **Verified:** 39/39 .NET tests pass (up from 27).

### P7 — Seamless switch (hot-reload `active_provider`) ✅
**Files:** `Store.Api/Program.cs`
- Checkout endpoint reads `payments:active_provider` from runtime config (hot-reloaded by ASP.NET),
  falling back to the pack's stored provider.
- Webhook routing already keyed by `{provider}` route param — unaffected by active_provider changes.
- `MoneyRailConfigGate` already validates only the active provider's secret.
- **Verified:** parity test proves webhook routing uses explicit provider, not active_provider.

---

## Control Center go-live ✅ ALL DONE

1. ✅ **Cancel-safety test** — `prospector/store.py` now writes dossiers atomically
   (write-temp-then-rename). 3 tests in `tests/control_center/test_cancel_safety.py` verify:
   atomic-write leaves no partial file, cancelled subprocess doesn't corrupt state, runner cancel
   updates job status.
2. ⚠️ **Live vet smoke** — requires manual verification through the Streamlit UI (browser
   rendering can't be automated without Playwright). The Launcher page is wired; launch a vet
   and confirm live log streams and the dossier deep-link render.
3. ✅ **Golden regression from UI** — Parameters page "Run golden regression" button runs
   `pytest -k golden`. Verified: 15/15 golden tests pass, certification.json written on success.
4. ✅ **Retention sweep** — `runner.sweep_old_logs(retain_days=30)` prunes
   `store/control_center/runs/*.log` older than N days. 3 tests in
   `tests/control_center/test_runner.py::TestRetentionSweep` verify removal, retention, and
   empty-dir safety.

Deferred (unchanged): auth/multi-user, Prometheus/health endpoint, UI telemetry,
reverse-proxy/`--server.runOnSave=false` hardening.

---

## Final state
- **Python:** 283 passed, 1 skipped
- **.NET:** 39 passed (Store.Tests)
- **Golden regression:** 15 passed
- **New files:** `Store.Tests/Payments/ProviderParityTests.cs`,
  `Store.Api/Contracts/CheckoutRequest.cs`, `tests/control_center/test_cancel_safety.py`
- **Modified files:** `prospector/bridge.py`, `prospector/store.py`,
  `Store.Api/Program.cs`, `Store.Api/Contracts/PublishRequest.cs`,
  `Store.Api/Payments/StripeProvider.cs`, `Store.Web/src/pages/pack/[id].tsx`,
  `prospector/control_center/runner.py`, `tests/control_center/test_runner.py`
- **Ready for Claude review → commit.**

---

## Working agreement
- One phase per change. Build + tests green BEFORE handing a money-rail diff to Claude.
- Money-rail commits: Claude reviews, then commit with footer
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- If a provider/API call would spend real money, use test-mode keys; never live keys in tests.
