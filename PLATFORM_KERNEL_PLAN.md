# Platform Kernel — Synthesis & Extraction Plan

**Status:** approved direction (2026-06-19). Working name for the shared foundation: **Crux**
(placeholder, rename freely). This is the plan to stop re-writing the same cross-cutting services
(auth, payments, notifications, storage, audit, observability) in every project — TIE, haworks,
haworks-platform, Prospector, and everything after.

**Founder fence:** identity + money + contracts + migrations stay on Claude. Ideal to execute in a
fresh escalated session (Fable-5 at session start, `/clear` first to keep cache warm).

---

## 1. The decision (locked)

Build a **TIE-led shared library kernel**: a set of versioned, in-process .NET packages a host app
references via `dotnet add package`. NOT run-as-services, NOT a monorepo consolidation.

- **TIE** (`the-introduction-exchange`) is the **skeleton / primary donor** — cleanest reuse seams,
  genuine `Tie.SharedKernel`, real CI, build-enforced architecture (Roslyn Tie001-003 + NetArchTest),
  production-hardened money rail (Stripe Connect escrow, Polly, idempotency-first, MoneyRailConfigGate,
  Temporal workflow), 3 social providers (Google, LinkedIn OIDC, Apple via bespoke validator).
- **haworks-platform** is the **heavy platform + parts donor** — kept intact as the microservices
  platform for when genuinely needed; specific modules are lifted into the kernel where it beats TIE
  (observability, notifications, storage, and several genuinely-generic commerce modules).
- **haworks (RitualWorks) is RETIRED as a foundation.** Nothing survived the sweep that the other two
  don't do better. Its one gem (chunked upload + ClamAV) is exactly the storage model we are *dropping*.
  IdentityServer4 is EOL — must NOT be adopted. Mine ideas only.
- **Storage = CLOUD object store (S3 / R2 / Azure Blob / GCS / MinIO) with presigned URLs.** NOT
  chunked/multipart upload, NOT ClamAV, NOT media-processing pipelines.

---

## 2. What goes in the kernel (grounded in the haworks-platform sweep)

Source notation: **[TIE]**, **[HP]** = haworks-platform. Robustness 1-5.

### Core packages (KERNEL-CORE — no infra deps, ship first)
| Package | Source | Contents | Score |
|---|---|---|---|
| `Crux.Kernel` | [TIE] SharedKernel + [HP] BuildingBlocks | `Result<T>`/`Error` (strip HP's 215 lines of domain error constants), `AuditableEntity`, `ICurrentUserService`, MediatR behaviors (validation / logging / **telemetry** / idempotency), `ConfigJwtSigningKeyProvider`, claims/httpcontext extensions | 4 |
| `Crux.Observability` | [HP] BuildingBlocks | OTel wiring + `CorrelationIdMiddleware` + correlation http-handler + `ActivityEnricher` + `AddDbHealthCheck<T>`. Parameterize the hardcoded 18-service meter list. Best-of-three. | 5 |
| `Crux.Resilience` | [HP] | Polly v8 `AddStandardResilienceHandler` + `IResilienceMetrics`/null-object. **Drop HP's duplicate custom Polly v7 factory.** | 4 |
| `Crux.Idempotency` | [HP] | `IIdempotencyStore` interface + `IdempotencyBehavior` (already EF-provider-agnostic, runs on sqlite) + new `EfIdempotencyStore<TContext>`. **Leave `PostgresIdempotencyStore` behind (xmax is Postgres-only).** | 4 |

### Founder-fence packages (identity + money — Claude-owned)
| Package | Source | Contents | Score |
|---|---|---|---|
| `Crux.Identity` | [TIE] primary | Cookie/session auth, Google + LinkedIn OIDC + Apple (`AppleTokenValidator`). Cleaner seam than HP. **Optional graft from [HP]:** JWKS endpoint + rotating key ring + service-to-service tokens if multi-service auth is needed later. DROP IdentityServer4. | 4 |
| `Crux.Payments.Stripe` | [TIE] primary | Single-provider Stripe, escrow-grade, Polly, idempotency-first, MoneyRailConfigGate. | 4 |
| `Crux.Payments.MultiProvider` *(escalation, optional)* | [HP] | `IPaymentGateway` multi-provider (Stripe + PayPal) + webhook workers. Only for projects that need >1 PSP. | 3 |

### Capability packages (HP beats TIE here)
| Package | Source | Contents + strip list | Score |
|---|---|---|---|
| `Crux.Storage` | [HP] `src/Media` | `IS3Service` → rename **`IBlobStore`** with only `GetUploadPresignUrl` / `GetDownloadPresignUrl` / `Delete`. Already R2/S3/MinIO-compatible (`ServiceUrl` + `Region:auto`). **Strip:** multipart flow, ClamAV/quarantine, ImageSharp/FFmpeg processing, `MediaVersion`, MassTransit outbox. Collapse status enum to Pending→Active/Failed/Deleted. ~2 days. | 4 |
| `Crux.Notifications` | [HP] `src/Notifications` | 2-layer provider seam (`IEmailProvider`+gateway) with SES / SendGrid / Twilio / FCM + Scriban templating + suppression + preferences + idempotency + per-provider circuit breakers. **Strip/refactor:** invert mandatory-bus dispatch into a direct `NotificationDispatchService` (today the handler only publishes to RabbitMQ — no sync send path); strip Vault; strip app-specific consumers (`RefundEmailConsumer`, `SecretExpiryWarningConsumer`). ~3 days. | 4 |

### Optional commerce packages (generic enough to reuse; opt-in per project)
| Package | Source | Why reusable / strip | Score |
|---|---|---|---|
| `Crux.Commerce.Checkout` | [HP] CheckoutOrchestrator | Verified zero haworks domain language — a clean B2C stock⇄payment saga. Highest reuse ROI. Needs the bus (opt-in `Crux.Messaging`). | 4 |
| `Crux.Commerce.Catalog` | [HP] Catalog | Generic Product/Category/Review/StockReservation. Strip demo controllers, `ProductCacheInvalidatedEvent`, cross-context `CheckoutItemData` embedding (→ local `LineItem`), `SagaId`/saga-propagation fields. | 4 |
| `Crux.Commerce.Pricing` | [HP] Pricing | Tiered discounts + promo codes + pluggable `ITaxCalculator`. Replace `ICatalogPricingClient` HTTP coupling with a caller-supplied `IProductPriceSource`. Add platform-fee as a first-class discount type. | 3 |
| `Crux.Commerce.Payouts` | [HP] Payouts | Double-entry ledger + `IPayoutGateway` (Stripe Connect) for two-sided marketplaces. Postgres-only locking (`FOR UPDATE SKIP LOCKED`). | 3 |
| `Crux.Commerce.Merchant` | [HP] Merchant | Cleanest generic vendor-onboarding domain. Replace `Haworks.BuildingBlocks.Authentication` dep with the kernel's auth abstraction. | 4 |

### Opt-in infra adapters (NOT default deps)
| Package | Source | Note |
|---|---|---|
| `Crux.Messaging` | [HP] Messaging | All-MassTransit. Kernel default ships only an `IDomainEventPublisher` interface (TIE's outbox is cleaner). This package is the MassTransit implementation. |
| `Crux.Vault` | [HP] Vault (20 files) | AppRole + dynamic DB creds + K8s sidecar. Kernel default = config secrets via `ConfigJwtSigningKeyProvider`; this is the opt-in escalation. |

### Explicitly NOT extracted (stay haworks-platform microservices / dropped)
- **Audit** (partitioned tables + bus ingestion), **Privacy** (GDPR erasure saga), **Scheduler**
  (Hangfire welded into the domain via `HangfireJobId`) — stay as services; copy patterns, not code.
- **Orders** — copy the `Order` domain state machine as a reference pattern; the app-layer consumers are
  too coupled to haworks peer contracts to package.
- **Location** — REFERENCE-ONLY until the in-memory `Point.Distance()` full-table-scan bug is fixed.
- **haworks `IS3Service` chunked/ClamAV pipeline** — dropped by decision.

---

## 3. Step 0 — must-fix in haworks-platform BEFORE extraction
These are load-bearing bugs that will poison the kernel if lifted as-is:
1. **`SagaPersistenceInterceptor` is registered on everyone** via `ServiceDefaults.cs:80` — any project
   calling `AddServiceDefaults` silently inherits a broken transitive MassTransit dependency even if it
   never uses the bus. Make it an explicit `AddMassTransitObservability()` opt-in first.
2. **Dual Polly stacks** — v8 `AddStandardResilienceHandler` runs globally AND the custom v7 factory is a
   DI service; HTTP calls can hit two retry loops. Pick v8, delete the v7 factory.
3. **`Error.cs` domain-constant dump** — move `Error.Payment.*`/`Error.Auth.*`/`Error.Vault.*` out of the
   shared project into each domain before lifting `Result`/`Error`.
4. **`HangfireJobId` on the `ScheduledEvent` domain entity** — infra leaked into domain (confirms Scheduler
   isn't extractable; no fix needed for the kernel, just don't extract it).

---

## 4. Distribution
- Private **GitHub Packages NuGet feed** under `chidionyema` org. `dotnet nuget add source` once per dev
  machine + CI; consume via `dotnet add package Crux.*`.
- **SemVer**, strict. Founder-fence packages (`Crux.Identity`, `Crux.Payments.*`) get a CI gate:
  no publish without Claude review of the diff (golden-set / contract tests green).
- One kernel repo (`chidionyema/crux`) with the package projects + their tests (port HP's Pact
  contract tests + TIE's analyzers + golden-journey CI). Aspire/Helm stay in haworks-platform.

---

## 5. Extraction order (each step independently shippable)
1. **Step 0 fixes** in haworks-platform (above). Small, mechanical, de-risks everything.
2. **`Crux.Kernel` + `Crux.Observability` + `Crux.Resilience` + `Crux.Idempotency`** —
   no infra deps; prove the feed + consumption model with the cheapest packages.
3. **`Crux.Storage`** (R2 presign) — first capability; Prospector already wants R2 download URLs.
4. **`Crux.Identity`** (founder fence) — TIE-led; this is what kills the per-project auth rewrite.
5. **`Crux.Payments.Stripe`** (founder fence) — eventually replaces Prospector's hand-rolled rail.
6. **`Crux.Notifications`** — invert the bus dependency; Prospector swaps Postmark behind the seam.
7. **Optional commerce packages** — only when a project needs them.

---

## 6. Prospector as consumer #1
- Today: account-less guest checkout, hand-rolled ~200-line StripeProvider, sqlite, R2 download via
  `/download/{token}`. Wiring order:
  - Adopt `Crux.Storage` for the R2 presign leg (smallest, safest first cut).
  - Adopt `Crux.Identity` to restore accounts + social login — this **replaces** the from-scratch
    `store_platform/ACCOUNTS_RESTORE_PLAN.md` (scrapped: don't build identity from zero).
  - Later, swap the hand-rolled Stripe for `Crux.Payments.Stripe`.
- Keep guest checkout working throughout. Money tables must get zero migration diff when the Users table
  lands. Uncomment the matching identity entries in `.protected-paths` as each file lands (silent-deletion
  guard stays active).

---

## 7. Security audit (hard requirement, after the foundation lands)
Comprehensive audit once extraction is in place. Reuse haworks-platform's
`docs/agent-briefs/audit-protocol.md` + `docs/reviews/`. Focus: the founder-fence packages
(`Crux.Identity`, `Crux.Payments.*`) — OAuth state/PKCE, open-redirect, unverified-email trust,
duplicate-account race, webhook signature validation, secret handling, idempotency under concurrency.

---

## 8. Open naming decision
"Crux" is a placeholder. Pick a final name before the first publish (it bakes into namespaces +
package IDs). Everything else above is decided.
