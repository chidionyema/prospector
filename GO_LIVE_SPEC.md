# Prospector — Go-Live Specification & Production-Readiness Assessment

**Date:** 2026-06-16
**Author:** Engineering (Claude, founder-reviewed)
**Status:** DRAFT for go/no-go decision
**Scope:** Whole system — engine, APIs, storefront UI, payment, fulfilment, legal, ops.

---

## ⚠️ STATUS UPDATE — 2026-06-18 (supersedes the "sell-and-deliver chain is not built" verdict below)

The fulfilment chain this document describes as the P0 showstopper **is now built and tested**. Treat the sections below as historical context; this banner is the current truth.

**Built since this doc was written (all in the .NET store + Python bridge, founder-reviewed):**
- `Order` / `Entitlement` / `OrderStatus` / `EntitlementStatus` domain entities + migrations.
- `FulfilmentService` — webhook → atomic `SalesAudit` + `Order` + `Entitlement` + `GrantToken`, idempotent on the unique transaction id, never drops a paid sale.
- Delivery endpoints — `/orders/{token}`, `/api/orders/{token}` (JSON), `/download/{token}` (presigned 5-min URL, Active-only).
- Magic-link email — `IEmailSender` / `PostmarkEmailSender`, dispatched after fulfilment.
- Content upload — `R2Uploader` (boto3, content-addressed) + the **list-only-after-upload** invariant enforced on both sides.
- Buyer-facing UI — `pages/orders/[token].tsx`, `success.tsx`.
- Money-rail hardening (2026-06-18 review): no committed default internal key (fail-closed); config gate validates `Stripe:ApiKey` + `WebhookSecret` at boot; Stripe provisioning is idempotent and raises a domain `ProvisioningError`; webhook dead-code removed; download authorizes positively on `Active`.

**Genuinely remaining to take money (config / legal / ops — not code):**
- Decision: Merchant-of-Record / payment provider for launch (Paddle-MoR safest), object storage, email provider, local-engine/hosted-storefront split sign-off.
- Live payment keys + webhook secrets wired (gate now enforces presence at boot).
- Legal: real reviewed ToS/Privacy (shells exist), **a refund policy**, and a point-of-sale "not financial advice" disclaimer.
- CI golden-set gate (no CI yet) + an end-to-end signal→PASS→publish→buy→download→refund test.
- Rotate the R2 + Gemini keys flagged exposed earlier.

---

## 0. TL;DR — Go/No-Go Verdict

**Verdict: NOT go-live ready for *taking money* today. The engine is ready; the sell-and-deliver chain is not.**

The system is much further along than a prototype: there is a working grounded vetting **engine**, a **FastAPI** read API, a **.NET Store API + SQLite**, and a **Next.js storefront** with Paddle checkout scaffolding. The blocker is not "build the product" — it's **three specific holes that sit between "buyer clicks Buy" and "buyer receives what they paid for."**

| Layer | State | Go-live readiness |
|---|---|---|
| Vetting engine (CLI factory) | Production-grade, well-tested | ✅ Ready (supervised) |
| Publish → bundle → catalog wiring | Built end-to-end | 🟡 Mostly (upload stubbed) |
| FastAPI read API | Real endpoints, tests broken | 🟡 Code ready, unverified |
| .NET Store API + DB | Running, persistent | ✅ Ready |
| Next.js storefront UI | Browsable, checkout scaffolded | 🟡 Demo-ready, not sale-ready |
| Payment (Paddle) | Sandbox-only | 🔴 Not live |
| **Fulfilment / delivery** | **Absent** | 🔴 **Showstopper** |
| Entitlements / buyer identity | Absent (test-token stub) | 🔴 Showstopper |
| Legal / disclaimer layer | Absent | 🔴 Showstopper for paid claims |
| CI / automated regression gate | Absent | 🟡 Process risk |

**Bottom line:** A buyer can browse the storefront and reach a checkout, but **payment is sandbox-only and there is no way to deliver the purchased pack** — money would land with no fulfilment. Closing the P0 list below is what stands between "demo" and "live."

---

## 1. What Actually Exists (verified inventory)

This is not a greenfield spec; it documents and hardens what is already built. Verified against source:

### 1.1 Vetting engine (Python) — `prospector/`
- CLI orchestrator `run.py` with `vet`, `signal`, `generate`, `report`, `diagnose`, `discover`, `operators`.
- The moat: `verify.py` (six grounded checks, kill-fast), `kill_filter.py`, `score.py`, `adversarial`.
- Resilience: `breaker.py` (circuit breaker), `health.py` (cross-run quota windows, `store/provider_health.json`), `FallbackOperator` chains.
- Observability: `telemetry.py` (JSON audit `store/prospector.jsonl`, per-provider spend/tokens), `report.py`, `progress.py`.
- Config-driven throughout: `config.yaml` + `config.py` (no hardcoded thresholds/secrets).
- Persistence: `store.py` — SQLite index + per-candidate JSON dossiers (`store/dossiers/*.json`), legacy listings (`store/listings/*.json`).

### 1.2 Publish / packaging bridge (Python)
- `publish/publish.py` → `prospector/bridge.py` (`EngineBridge.publish_pass`): on PASS, builds a ZIP bundle, creates Paddle Product/Price (£30 = 3000 pence), upserts to the .NET Store catalog.
- `prospector/packs.py` (`compose_packs`) builds **3 tiered packs** (Scout/Operator/Founder) — **ORPHANED**: zero callers; the live path ships one hardcoded £30 pack.

### 1.3 FastAPI read API (Python) — `prospector/api.py`
- `GET /v1/listings`, `/v1/listings/{id}`, `/v1/dossiers/{id}` (gated), `/v1/health`, `/v1/metrics`, `/v1/usage`.
- Entitlement gating is a **stub**: `Bearer test-token` grants everything.

### 1.4 .NET Store API — `store_platform/src/Store.Api/` (.NET 9, EF Core, SQLite)
- `GET /catalog`, `GET /catalog/{id}`, `POST /internal/catalog` (engine-only upsert), `POST /webhooks/paddle`.
- Tables: `Packs` (Id, Title, OneLine, DossierRef, PricePence, PaddleProductId/PriceId, IsListed, CreatedAt), `SalesAudits` (PaddleTransactionId unique, AmountPence, Country, OccurredAt).
- **No download / content / entitlement endpoint exists.**

### 1.5 Storefront UI — `store_platform/src/Store.Web/` (Next.js 16, React 19, TS, Tailwind)
- Pages: `/` (catalog grid), `/pack/[id]` (detail + checkout sidebar), `/privacy`, `/terms`, `/faq`, `/how-it-works`.
- Data: `getServerSideProps` → `fetchCatalog()` / `fetchPackDetails(id)` against the .NET Store API.
- Payments: Stripe SDK loaded + Paddle configured, **sandbox-only**.

---

## 2. The Critical Architecture Decision (must resolve first)

`CLAUDE.md` states the system runs **locally / within the Claude Code subscription — "No hosted service ... no infrastructure beyond your own server."** Going live with a **storefront that takes payments** is fundamentally at odds with "local-only," because the storefront, Store API, DB, and Paddle webhook receiver **must be internet-reachable and continuously available**.

**Resolution to adopt for go-live (recommended split):**
- **Engine stays local & supervised** — generation/vetting run under operator watch (preserves the liability backstop and the founder fence). It only ever *pushes* to the catalog.
- **Catalog + storefront + payment + fulfilment get hosted** — these are the only components that need uptime/public exposure. They hold *no* model keys and *cannot* manufacture a PASS; they only display and deliver what the local engine published.

This split keeps the operating rules intact (moat & money-decisions stay with the supervised engine) while allowing a real storefront. **The spec below assumes this split.** This decision must be explicitly signed off before any hosting spend.

---

## 3. Production-Readiness by Component

Readiness % are engineering estimates, not measured SLAs.

### 3.1 Engine — ✅ READY for supervised batch (~90%)
**Evidence:** dual-layer recovery (`vet --resume` for moat DEFER + provisional re-vet; `generate --resume` for chain exhaustion, pending signals in `signals/pending/`); env-var-first secrets with `.env.example` and `.gitignore` coverage; per-provider breaker + persistent health windows; full JSON audit + cost reports; fully config-driven.

**Residual risks (accept with mitigations, not blockers):**
1. **Search-outage DEFERs aren't queued for auto-resume** like generation exhaustion is — operator must watch `retrieval_failed` events in `store/prospector.jsonl`. *(P2: unify search-outage into the resume queue.)*
2. **Provisional PASS trust boundary** — a PASS ruled by the cheap tail persists in the catalogue with `provisional=true`; it must never publish. Verify the publish path hard-blocks `provisional` and surface a provisional count in reports. *(P1 — confirm the guard.)*
3. **Spend cap is a soft pre-check** (estimate-based, in-flight candidates not aborted). Set `daily_cap_usd` ~10% under the real billing limit. *(P2.)*

### 3.2 FastAPI read API — 🟡 CODE READY, UNVERIFIED (~60%)
Endpoints are real and load from `store/listings`. **But** `tests/integration/test_api.py` fails at collection (`TypeError: Client.__init__() got an unexpected keyword argument 'app'` — Starlette/httpx `TestClient` version drift), so **5 endpoint tests (listings, dossier gating ±, health, metrics) do not run**. The access-control gate is therefore unverified. *(P0 to fix tests; P0 to replace the `test-token` stub before any gated content is served.)*

### 3.3 .NET Store API + DB — ✅ READY (~80%)
Running, persistent, serves the UI, accepts engine publishes, records sales audits. Missing the delivery/entitlement endpoints (covered under P0 fulfilment).

### 3.4 Storefront UI — 🟡 DEMO-READY, NOT SALE-READY (see §4)

### 3.5 Payment (Paddle) — 🔴 SANDBOX-ONLY
Product/price creation, webhook signature verification, and `SalesAudits` logging exist, but it's sandbox-configured and the **bundle upload is simulated** (`bridge.py:90-92`). No live credentials, no sandbox→prod toggle exercised. *(P0.)*

### 3.6 Fulfilment / delivery — 🔴 ABSENT (the showstopper)
**Current dead-end:** buyer pays → `transaction.completed` webhook → `SalesAudits` row inserted → **nothing downstream.** No content endpoint, no entitlement grant, no buyer identity, no email/download link. The buyer has paid and **cannot retrieve the pack.** *(P0 — see §5.1.)*

---

## 4. UI Production-Readiness Verdict (explicit, as requested)

**Is the UI ready for production? NO — it is demo-ready, not sale-ready. ~65%.**

**What works:** the storefront renders a real catalog from the Store API, pack detail pages load, the checkout sidebar and Paddle/Stripe SDK are wired, and the static pages (`/privacy`, `/terms`, `/faq`, `/how-it-works`) exist as shells.

**What blocks production:**
1. **No completable purchase** — Paddle is sandbox-only; a real buyer cannot pay. (P0)
2. **No post-purchase experience** — no order confirmation, no "my purchases"/account, no download screen. Even if payment succeeded, the UI has nowhere to deliver the pack. (P0)
3. **No auth / buyer identity** — no login, no session, no entitlement check on gated content (mirrors the API `test-token` stub). (P0)
4. **Legal pages are shells** — `/terms` and `/privacy` exist as routes but need real, lawyer-reviewed content for a product selling factual business claims, plus a visible "not financial advice" disclaimer at point of sale. (P0/legal)
5. **No grounding transparency surfaced** — listings don't show source count / verification date / confidence, which is the product's core differentiator *and* its liability shield. (P1)
6. **Unverified production concerns:** error/empty/loading states for API-down, SEO/meta, accessibility, analytics/consent, mobile QA, and a tested production build + env config. (P1)

**One-line:** *The UI can be shown to a stakeholder today; it cannot safely take a stranger's money today.*

---

## 5. P0 — Blockers (must close before taking a single payment)

### 5.1 Fulfilment chain (CRITICAL — no revenue without it)
Build the path from paid → delivered:
1. **Content storage & upload:** finish `bridge.py` bundle upload — either Paddle's file/fulfilment mechanism *or* (recommended) upload the ZIP to private object storage (e.g., S3/R2) and store a key on the `Pack`.
2. **Entitlement on payment:** in `WebhookEndpoints.HandlePaddleWebhook`, on `transaction.completed`: look up the `Pack` by Paddle product id, create a **buyer/order/entitlement** record (new table), and mint a one-time, expiring download grant (or account-bound license).
3. **Delivery:** add `GET /catalog/{id}/download` (or `/orders/{token}/download`) that validates the entitlement and returns a short-lived presigned URL; and/or email the buyer a download link.
4. **UI:** order-confirmation page + download screen (and/or "check your email").
**Acceptance:** a sandbox purchase results in the buyer downloading exactly the pack they bought, and only that pack; an un-purchased pack returns 403.

### 5.2 Entitlements & buyer identity (CRITICAL)
Replace the `Bearer test-token` stub (FastAPI `api.py` and UI) with real auth (accounts or signed, scoped tokens issued on purchase). Gated dossier/content access must verify a real entitlement.
**Acceptance:** gated endpoints deny without a valid entitlement; the broken API tests are fixed and prove both the positive and negative gate.

### 5.3 Live payments (CRITICAL)
Move Paddle from sandbox to live: real credentials (in secrets, **not** committed; add to `.env.example`), prod toggle, **webhook signature verification confirmed against live keys**, idempotent webhook handling (the `PaddleTransactionId` unique constraint helps — verify the upsert is truly idempotent), refunds/chargeback handling defined.
**Acceptance:** a real low-value live transaction completes end-to-end (pay → entitle → deliver) and is reconciled in `SalesAudits`.

### 5.4 Legal / compliance layer (CRITICAL for selling claims)
- Real, reviewed **Terms of Service, Privacy Policy, Refund Policy**, and a prominent **"informational only — not financial/professional advice"** disclaimer at point of sale and in the pack.
- **Surface grounding metadata** on every listing/dossier shown to a buyer: source count, verification date, `reverify_due_at`, confidence — turning the internal source-or-die guarantee into a visible (and defensible) buyer-facing attestation.
- VAT/sales-tax handling (Paddle as Merchant of Record covers much of this — confirm and document).
**Acceptance:** no paid claim is shown without visible provenance + disclaimer; policies are linked from checkout.

### 5.5 Fix the broken API test harness (CRITICAL — unblocks verification of 5.2)
Resolve the `TestClient(app=...)` incompatibility (pin/upgrade FastAPI/Starlette/httpx, or switch to `httpx.ASGITransport`). Remove it from the pytest ignore list.
**Acceptance:** `tests/integration/test_api.py` collects and passes in the standard suite.

---

## 6. P1 — Important (close during/just after soft launch)

1. **CI/CD with a hard golden-set gate.** There is **no CI**. The golden-set regression (`tests/test_golden_set.py`, 100% discrimination on 9 mixed-sector cases) is the truth-veto and is currently enforced by *discipline only*. Add a pipeline (GitHub Actions) that runs the full suite + golden set on every PR and **blocks merge on <100% discrimination**. *(Process risk → silent veracity regression.)*
2. **Confirm the `provisional` publish-block** end-to-end (a provisional PASS must never reach the catalog).
3. **Decide packs.py fate:** wire the 3-tier `compose_packs` into publish, or delete it. Orphaned code that looks load-bearing is a trap.
4. **UI production hardening:** API-down/empty/loading states, error boundaries, SEO/meta, analytics + cookie consent, accessibility pass, mobile QA, tested prod build.
5. **End-to-end integration test:** signal → vet → PASS → publish → catalog → (mock) purchase → download. (`tests/behavioural/test_publish.py:76` already flags this TODO.)
6. **Secrets completeness:** add Paddle (and any storefront) keys to `.env.example`; document the hosted-side secret store.

## 7. P2 — Hardening / post-launch

1. Unify search-outage DEFERs into the resume queue.
2. Harden spend cap (in-flight abort or tighter buffer).
3. Operational runbook additions: golden-set-failure triage, config rollback, gate-regression diagnosis.
4. Load/stress test concurrent vetting and the storefront.
5. Backups for both SQLite stores (engine `prospector.db`, Store `store.db`) and the dossier/bundle files.
6. Monitoring/alerting on the hosted side (uptime, webhook failures, 5xx, payment-without-fulfilment alarm).

---

## 8. Security & Data (cross-cutting checklist)

- [ ] No secrets in git (verified: `.env*`, `*.key`, `*.pem` gitignored; keys env-var-first). Re-audit before hosting.
- [ ] Hosted services hold **no LLM/model keys** (founder fence — only the local engine does).
- [ ] Paddle webhook signature verification confirmed on live keys; endpoint rate-limited.
- [ ] Download grants are short-lived, single-pack-scoped, and non-enumerable.
- [ ] PII minimised: buyer email/identity stored only as needed; privacy policy reflects reality.
- [ ] TLS everywhere; CORS locked to the storefront origin on both APIs.
- [ ] Backups + restore tested for both SQLite DBs and bundle storage.

---

## 9. Phased Go-Live Plan

**Phase 0 — Decision & scope (0.5 day).** Sign off the local-engine / hosted-storefront split (§2). Choose content-delivery mechanism (object storage vs Paddle fulfilment).

**Phase 1 — Close the money/delivery loop (the P0 core).** 5.1 fulfilment, 5.2 entitlements, 5.5 API tests. *Exit:* sandbox purchase → entitled download works and is tested.

**Phase 2 — Payments + legal.** 5.3 live Paddle, 5.4 legal/disclaimer/provenance surfacing. *Exit:* one real low-value live sale completes end-to-end with policies in place.

**Phase 3 — Verification gate + UI hardening.** P1 CI/golden gate, provisional block, UI prod states, e2e test. *Exit:* green CI blocks regressions; UI handles failure modes.

**Phase 4 — Soft launch (limited).** Hosted, live, monitored, small audience. Watch payment-without-fulfilment alarm, webhook failures, spend, and provisional counts. *Exit:* N clean sales, zero fulfilment failures.

**Phase 5 — Hardening (P2)** in the background.

---

## 10. Go / No-Go Checklist (sign-off gate before Phase 4)

- [ ] Buyer can complete a **live** purchase and **download the exact pack** they bought; un-purchased packs 403.
- [ ] Gated API/UI access verified by **passing** positive + negative entitlement tests.
- [ ] Paddle live webhook signature-verified, idempotent, reconciled in `SalesAudits`.
- [ ] ToS / Privacy / Refund + "not advice" disclaimer live and linked from checkout.
- [ ] Every paid claim shows source count + verification date + confidence.
- [ ] CI runs full suite + golden set on every PR and blocks on <100% discrimination.
- [ ] `provisional` PASSes provably cannot publish.
- [ ] Secrets re-audited; hosted side holds no model keys; backups tested.
- [ ] Runbook covers: moat outage, golden-set failure, config rollback, payment-without-fulfilment.

---

## Appendix — Evidence map (key files)

- Engine moat: `prospector/verify.py`, `kill_filter.py`, `score.py`; orchestration `prospector/run.py`.
- Resilience: `prospector/breaker.py`, `prospector/health.py` (`store/provider_health.json`), `prospector/operator.py` (`FallbackOperator`).
- Observability: `prospector/telemetry.py` (`store/prospector.jsonl`), `prospector/report.py`.
- Publish/bridge: `publish/publish.py`, `prospector/bridge.py` (upload simulated @ L90-92), `prospector/packs.py` (orphaned `compose_packs`).
- FastAPI: `prospector/api.py` (`test-token` gate stub); broken tests `tests/integration/test_api.py`.
- Store API/DB: `store_platform/src/Store.Api/Program.cs` (`/catalog`, `/internal/catalog`), `Endpoints/WebhookEndpoints.cs` (`/webhooks/paddle`); SQLite `Packs` + `SalesAudits`.
- Storefront: `store_platform/src/Store.Web/` (`pages/index.tsx`, `pages/pack/[id].tsx`, `lib/client.ts`).
- Truth gate: `tests/test_golden_set.py`; source-or-die `prospector/verify.py` + `tests/behavioural/test_source_or_die.py`.
- Procedure/rules: `RUN.md`, `CLAUDE.md`, `README.md`.

> **Note on figures:** component readiness percentages are engineering estimates from a code walkthrough, not measured metrics. The current standard local test suite is **170 passing** (excludes the broken `tests/integration/test_api.py`); a fuller count (~183) includes the 5 API tests that do not currently collect.
