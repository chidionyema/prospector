# Launch Hardening — Execution Spec

**Date:** 2026-06-20
**Branch:** `launch-hardening-2026-06-18`
**Goal:** Close the four open launch issues — Stripe live cutover, admin-portal auth, continuous (supervised) generation, and kernel rollout — so the storefront can take real money safely.
**Founder fence:** Identity + money + contracts + migrations stay on Claude (Opus/Fable). Recon/UI scaffolding may delegate.
**Verify commands:**
- prospector engine: `.venv/bin/python -m pytest -q`
- Store.Api / Store.Tests: `cd store_platform/src && dotnet test Store.Tests/Store.Tests.csproj`
- Store.Web: `cd store_platform/src/Store.Web && npx tsc --noEmit && npm run build`
- kernel: `cd ~/Documents/code/keystone && dotnet build`

**Current state (verified 2026-06-20):**
- Security audit fixes applied + green (C# 61/61, Python 31, web typecheck clean). See the audit summary in this branch.
- Store on **Stripe TEST**, 11 packs reprovisioned to test prices. Webhook→entitlement→download wired; not yet proven with a real test-card event end to end.
- Admin portal = Streamlit app at `prospector/control_center/app.py`, **no auth**.
- Generation = on-demand only (`run.py` via `control_center/runner.py`); **no scheduler**.
- Kernel = `Crux.Storage` consumed by `Store.Api` only; 7 packages + 3 sibling projects unused.

---

## Workstream 0 — Stripe live cutover (THE launch blocker)

This is the only thing strictly between us and taking money. Follow `DEPLOYMENT.md` §7–§8; this spec adds the gates.

### 0.1 — Prove the money path end-to-end on TEST (BLOCKING, do first)
**Why:** unit/integration tests pass but no real Stripe event has driven the full leg. A green build hid two prod-breaking storage bugs already this branch — runtime proof is mandatory for money.
**Steps:**
1. Run API locally with test keys; `stripe listen --forward-to localhost:5291/webhooks/stripe`.
2. Buy a pack with test card `4242 4242 4242 4242`.
3. Assert, with evidence captured to `store/launch/test-card-proof.md`:
   - `checkout.session.completed` received and signature-verified (not 503).
   - `Order` row `Paid` + `Entitlement` row `Active` created (one each, idempotent on replay).
   - `GET /orders/{token}` returns a working download; the presigned URL is `*.r2.cloudflarestorage.com`, `X-Amz-Expires=300`.
   - **Underpayment guard fires:** replay the same event body with `amount_total` below `PricePence` (or a 100%-off coupon session) → entitlement is NOT granted, item lands in `unfulfilled`. (Proves the audit fix in real traffic.)
4. Trigger `charge.refunded` → entitlement flips `Revoked`, download returns 410.
**Acceptance:** all four observed against a running instance, screenshots/log excerpts in the proof file.

### 0.2 — Live key cutover
**Files:** `.env` (live `STRIPE_API_KEY`, `Stripe__WebhookSecret`), `Store.Web/.env.local` (`NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` = live `pk_live_`).
**Steps:**
1. Register the **live** webhook endpoint in the Stripe dashboard; put its signing secret in `Stripe:WebhookSecret`.
2. Re-run `store_platform/scripts/reprovision_stripe.py` with **live** keys → live `price_…` ids on all 11 packs.
3. Confirm `MoneyRailConfigGate` boots in `Production` (it will throw if any key is missing or a dev placeholder — now including `Paddle:WebhookSecret`, per the audit fix).
4. Set `payments:active_provider=stripe` (Paddle stays the documented rollback; if ever reactivated, see WS-note below on CSP).
**Acceptance:** API boots in `Production` with live keys; one real low-value live purchase (then refund) completes the full leg; `git grep` confirms no `sk_live_`/`whsec_` committed.

### 0.3 — Pre-launch secret + config audit
- `git grep -nE 'sk_(live|test)_[A-Za-z0-9]{20,}|whsec_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}'` → must be empty.
- `.env`, `.env.local`, `content_store/` confirmed gitignored.
- `appsettings.Production.json` contains no secrets (env-sourced only).
**Acceptance:** clean grep; `MoneyRailConfigGate` is the single fail-closed gate for every required secret.

> **Paddle reactivation note (deferred):** if Paddle is ever switched back on, `Store.Web/next.config.ts` CSP `script-src` must add `https://cdn.paddle.com` (+ `*.paddle.com` for connect/frame) or its checkout silently hangs. Left tight (Stripe-only) deliberately for launch.

---

## Workstream 1 — Admin portal authentication

The Streamlit control center exposes config editing, run launching, catalogue/diagnostics, and cost data with **no gate**. Acceptable only bound to localhost; unsafe the moment it's reachable off-box. Make it safe to expose, and safe by default.

### 1.1 — Gate the app behind a single operator password (fail-closed)
**File:** new `prospector/control_center/auth.py`; call from `app.py` before any page renders.
**Design:**
- Read `CONTROL_CENTER_PASSWORD` from env (never committed). If unset → render a hard stop ("portal not configured") and `st.stop()`. **Fail closed**, mirroring the API's `require_admin`.
- Render a password field; compare with `hmac.compare_digest`. On success set `st.session_state["cc_authed"]=True`. Gate every page on that flag.
- Lockout: after N failed attempts in the session, `st.stop()` with a delay.
**File to edit:** `prospector/control_center/app.py` — insert `require_auth()` immediately after `inject_theme()` and before page dispatch (around line 84).
**Acceptance:** new test `tests/control_center/test_auth.py` — unset env → blocked; wrong password → blocked; right password → `cc_authed` set. App unchanged when authed.

### 1.2 — Bind to localhost by default; document the tunnel
**File:** `DEPLOYMENT.md` (new "Admin portal" section) + a launch script `scripts/run_control_center.sh`.
- Canonical launch: `streamlit run prospector/control_center/app.py --server.port 8601 --server.address 127.0.0.1`.
- Document remote access = SSH tunnel (`ssh -L 8601:localhost:8601 …`), never `0.0.0.0` exposure.
- Set `CONTROL_CENTER_PASSWORD` as a required env even for local, so the auth path is always exercised.
**Acceptance:** script binds 127.0.0.1; DEPLOYMENT.md states the tunnel pattern and the "never expose publicly" rule.

### 1.3 — Harden the run launcher
**File:** `prospector/control_center/runner.py`.
- Confirm `argv` is always a fixed list (no shell string interpolation of user input) — it builds `run.py` invocations; assert no `shell=True`. (Audit found none in engine; verify here too.)
- Cap concurrent jobs at 1 (already lock-guarded) and bound the per-job cost via the WS2 budget guard.
**Acceptance:** static check — no `shell=True`, argv is a list literal + validated args.

---

## Workstream 2 — Always-on generation (no human in the loop) — IMPLEMENTED 2026-06-20

> **Founder decision (2026-06-20):** generation runs **continuously and unattended** — no human in the loop. This deliberately revises the `CLAUDE.md` "supervised batches… not a 24/7 API" line. The liability backstop is preserved, but it is now **automated** (a daily spend ceiling + a filesystem kill switch) rather than a human watching each batch. Those two rails are what make unattended operation safe.

### 2.1 — Automated backstop guard — DONE
**File:** `prospector/scheduler/guard.py` (`SchedulerGuard` / `guard_check`).
- Daily spend ceiling from `config.yaml` `spend.daily_cap_usd`, computed from the **persistent** ledger `store/prospector.jsonl` (sum of today's `spend` events). *Critical:* it must read the on-disk ledger, not `telemetry.get_usage_summary()` — a fresh daemon/subprocess has an empty in-process counter, so an in-process check would never fire.
- Filesystem kill switch: `store/scheduler/PAUSE` halts all batches (mirrors the dropped Stripe `EnsureNotPausedAsync`).
- Overshoot is bounded to one batch (pre-run check).
**Acceptance (met):** `tests/scheduler/test_guard.py` — over-cap blocks, PAUSE blocks, today-only windowing, malformed-line tolerance, cap inclusive. 9 tests green.

### 2.2 — Always-on daemon — DONE
**File:** `prospector/scheduler/run_scheduled.py` (`python -m prospector.scheduler.run_scheduled`).
- `--daemon [--interval N]` loops forever; each cycle re-evaluates the guard (so PAUSE / cap take effect with no restart), then runs one bounded blue-sky batch in-process via `run_signal("", cfg, k=batch_size, publish=True)` — reusing the engine entrypoint, not forking it.
- `--once [--dry-run]` runs a single tick (used by tests and smoke checks).
- Routes telemetry to `store/prospector.jsonl` so the guard's spend math sees real costs; logs each tick to `store/scheduler/ticks.jsonl`. Survives any single batch failure (DEFER on moat exhaustion is caught; the daemon keeps looping). Honours SIGTERM/SIGINT for clean `launchctl` stop.
**Acceptance (met):** `tests/scheduler/test_run_scheduled.py` — runs when permitted, skips when paused, dry-run never generates, survives generation error, daemon honours max-cycles + idles when paused. 7 tests green. `--once --dry-run` smoke against real config exits 0 and logs a tick.

### 2.3 — OS-level residency (launchd KeepAlive) — DONE
**File:** `deploy/com.prospector.scheduler.plist`.
- `KeepAlive=true` + `RunAtLoad=true` → a truly resident daemon; launchd restarts it if it dies. `--interval 7200` cadence. Logs to `store/scheduler/launchd.{out,err}.log`.
**Acceptance (met):** documented load/unload/pause in `DEPLOYMENT.md`. `touch store/scheduler/PAUSE` idles it; `rm` resumes; no restart needed.

**Operational caveat:** the moat (verify) needs the Claude/Gemini CLIs authenticated in the daemon's environment. If they aren't, generation DEFERs (does not crash) and work is recoverable via `vet --resume`. Confirm CLI auth survives in the launchd session before relying on unattended PASSes.

---

## Workstream 3 — Kernel rollout (Crux)

Today: `Crux.Storage` in `Store.Api` only. The plan (PLATFORM_KERNEL_PLAN.md) is a shared kernel across projects. Roll out by value, money/identity on the founder fence. **Do NOT rip-and-replace working money code to chase adoption** — adopt where it removes real duplication and is proven by tests.

### 3.0 — Fix the distribution model first (BLOCKING)
**Problem:** `Store.Api.csproj:24` references the kernel by relative cross-repo path (`..\..\..\..\keystone\src\Crux.Storage\Crux.Storage.csproj`). Builds on this machine only; breaks on CI/other machines/repo moves.
**Fix:** publish the kernel as a GitHub Packages NuGet feed (per the plan); switch `Store.Api` to a versioned `<PackageReference Include="Crux.Storage" Version="…" />`.
**Acceptance:** Store.Api builds from a clean checkout with no sibling `keystone/` repo present; CI green.

### 3.1 — Kernel test coverage (BLOCKING before consuming more packages)
**Problem (from handoff):** Crux.Kernel + Crux.Idempotency tests dirs are EMPTY; Identity has 8 tests, Payments.Stripe 0.
**Fix:** before any new consumer, each package being adopted must have tests proving its money/identity-critical behavior:
- **Crux.Payments.Stripe** (highest priority if adopted): webhook signature accept/reject, `ChargeId` extraction, capture/refund routing, the dropped kill-switch decision.
- **Crux.Idempotency**: dedup under concurrent duplicate.
**Acceptance:** `cd ~/Documents/code/keystone && dotnet test` green; no package consumed without coverage.

### 3.2 — Adoption order (each independently shippable, prove then move on)
1. **Crux.Observability / Crux.Resilience** (lowest risk, no money/identity): `AddCruxResilience()` in `Store.Api`; replace ad-hoc HttpClient policies. *Acceptance:* Store.Tests green, resilience metrics emit.
2. **Crux.Payments.Stripe** (founder fence, Claude-owned): evaluate replacing `Store.Api/Payments/StripeProvider.cs` with `AddCruxStripePayments()`. ONLY after 3.1 + a side-by-side proof that signature verify, amount-validation (the audit fix), idempotency, and refund-revocation behave identically. *Acceptance:* the full FulfilmentService + webhook test suite passes against the Crux gateway; the 0.1 money-path proof re-run green. If parity isn't provable, **do not adopt** — keep the in-house provider.
3. **Crux.Identity** (founder fence): only if/when the store reintroduces accounts. Auth was deliberately removed; do not add it back for adoption's sake. Deferred.
4. **Crux.Notifications**: adopt for the order-confirmation email path if it removes duplication.
**Acceptance per step:** consuming project builds + its money/identity tests pass; no behavior regression vs the in-house code it replaces.

### 3.3 — Sibling projects (TIE / ritualworks / haworks-platform)
Zero kernel references today. Out of scope for *this* launch — prospector is the beachhead and the launch target. Track as follow-up: adopt `Crux.Observability`/`Resilience` first in one sibling as the second proof point, after 3.0 (NuGet feed) lands. Do not block the store launch on this.

---

## Sequencing & ship gates

| Order | Item | Blocks launch? | Owner tier |
|------|------|----------------|-----------|
| 1 | WS0.1 money-path proof on TEST | **YES** | Claude (money) |
| 2 | WS0.2 live key cutover | **YES** | Claude + human (keys) |
| 3 | WS0.3 secret audit | **YES** | Claude |
| 4 | WS1.1–1.2 portal auth + localhost bind | YES if portal exposed | Claude |
| 5 | WS3.0 NuGet feed (de-fragilize build) | YES (CI/deploy reliability) | Claude |
| 6 | WS2 supervised scheduler | No (post-launch capability) | Claude + founder decision |
| 7 | WS3.1–3.3 kernel rollout | No (incremental, post-launch) | Claude (fence items) |

**Minimum to launch:** items 1–5. Items 6–7 are post-launch and need the founder decision called out in WS2/WS3.

## Risks
- **Money-path runtime bugs a green build hides** (already bit us twice). Mitigation: WS0.1 runtime proof is non-negotiable.
- **Portal accidental exposure.** Mitigation: fail-closed auth + localhost default; never `0.0.0.0`.
- **Scheduler runaway cost.** Mitigation: budget guard + `PAUSE` switch + interval (not KeepAlive) cadence.
- **Kernel adoption regressing money code.** Mitigation: parity proof before replacing StripeProvider; abandon adoption if parity unprovable.
