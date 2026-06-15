# Platform Modules — compose, don't rebuild

**Status:** spec (manager-authored) — **ACTIVE as an independent track (Track 2).** Decoupled from the £30 store as of 2026-06-15.
**Author role:** manager (Claude). **Implements:** delegate, except the Identity & Payments modules (founder-fenced — money/identity → Claude). See `AGENTS.md` §0.
**Date:** 2026-06-15.

> **⚠️ Reconciling note (2026-06-15): two tracks, not one. This library is now justified on its own, not by the store.**
> This was written with the £30 store as **consumer #1**. The store then chose a **delivering Merchant of Record (Paddle) from day one** (`specs/stage6-storefront-platform.md` §0), which **hosts checkout, tax, AND file delivery** — deleting the store's need for `Identity`, `Payments`, `SecureDelivery`, `Entitlements`, and delivery-`Notifications`.
>
> **The user's call (2026-06-15): build BOTH.** So the work splits into two independent tracks:
> - **Track 1 — the store** ships on Paddle and **composes none of these modules.** It never waits on this library. (`specs/stage6-storefront-platform.md`.)
> - **Track 2 — this library** is built as a **standalone platform investment for FUTURE products** ("harvest once, reuse forever"), NOT to serve the store. Its consumer is the *next* product that needs **first-party** payments/identity/delivery (or a deliberate move off a MoR). Until that product exists its consumer is the **bare sample consumer** of §2.6 — that is sufficient justification under "build the reusable platform as a goal in its own right."
>
> **Discipline:** do not contort module surfaces to fit the store (it isn't a consumer), and do not let this track slow the store. Recommended sequencing: **ship the store first** (days), then run this track (Kernel → Engineering → Identity → …, §7), delegating non-fenced modules. The donor repos stay untouched throughout.

---

## 0. The shift

We have production-ready code spread across two repos. Instead of lifting it into one store and stopping, we **package each capability as a versioned, drop-in .NET module**. A new project then **composes** the modules it needs — `AddIdentity()`, `AddPayments()`, `AddSecureDelivery()` — and writes only its own domain. We do the harvesting **once**; we never repeat this exercise.

> Donor repos (`/Users/chidionyema/Desktop/haworks-platform`, `/Users/chidionyema/Documents/code/the-introduction-exchange`) stay **untouched**. We extract *into* a new module library; we do not modify or delete the originals.

---

## 1. Principle: a composable platform

- **Compose over build.** A new product = pick modules + write the domain glue. No re-implementing auth, payments, file delivery, email.
- **Harvest once, reuse forever.** Each module is extracted, decoupled, tested, and versioned a single time.
- **Abstractions are the product.** Consumers depend on `.Abstractions` (interfaces); implementations are swappable. This is what makes a module *drop-in* rather than *copy-paste*.
- **No infra lock-in.** A module must run with **zero external infra by default** (in-memory cache, config-based keys, no message bus). Vault, RabbitMQ, Redis are **opt-in extensions**, never hard dependencies. (This is the single biggest decoupling finding — see §6.)
- **Local-first.** Packages publish to a **local/private NuGet feed**; no hosted dependency. Honours CLAUDE.md "the entire system runs locally / no infrastructure beyond your own."

---

## 2. The packaging contract (every module obeys this)

This is the heart of the spec — the convention that makes modules interchangeable.

### 2.1 Package shape
Each capability ships as a small family under one house namespace `<House>` (name TBD — §9):

```
<House>.<Module>.Abstractions   ← interfaces, DTOs, options classes, domain contracts. Consumers depend on THIS.
<House>.<Module>                ← default implementation (EF, services, AddXxx()).
<House>.<Module>.<Infra>        ← OPT-IN infra adapters, one per concern: .Vault, .Messaging, .Redis, .Aws…
```

A consumer that just wants auth references `<House>.Identity` (which transitively pulls `.Abstractions`). A consumer that wants Vault-backed key rotation *also* references `<House>.Identity.Vault` and calls `.WithVault()`.

### 2.2 DI convention (the drop-in surface)
Every module exposes exactly one composition root method, matching the pattern both donors already use (`Identity.Infrastructure/DependencyInjection.cs:15`, `Identity.Application/DependencyInjection.cs:10`):

```csharp
services.AddIdentity(configuration);                 // sensible zero-infra defaults
services.AddIdentity(configuration).WithVault();     // opt-in infra
services.AddPayments(configuration).WithStripe();    // provider chosen explicitly
```

- Config bound via **`IOptions<T>` + `.ValidateDataAnnotations().ValidateOnStart()`** (already done in `Identity.Application/DependencyInjection.cs` for `JwtOptions` — adopt as the standard).
- Each module documents its **config schema** and **the services the consumer must supply** (e.g. an `IEmailSender`, a `DbContext`).

### 2.3 EF / persistence — schema-per-module
- A module that owns data owns its **EF schema** (haworks Identity uses schema `identity`, `AppIdentityDbContext.cs:58`) and its **own migrations** folder.
- **Two consumption modes**, both supported: (a) the module owns its `DbContext` (default, simplest drop-in); (b) advanced — the consumer composes the module's entity configs into a shared `DbContext`. Pick (a) for v1; document (b) as the advanced path.

### 2.4 The decoupling rule (non-negotiable for drop-in)
A module may depend only on: the BCL, ASP.NET Core, EF Core, and standard libraries (MediatR, FluentValidation, the relevant SDK e.g. Stripe.net). It may **not** hard-depend on:
- a secrets manager (Vault) → abstract behind `IJwtSigningKeyProvider`-style interface, default to config; Vault is a `.Vault` adapter.
- a message bus (MassTransit/RabbitMQ) → cross-module events go through an **in-process outbox dispatcher** by default; MassTransit is a `.Messaging` adapter.
- a distributed cache (Redis) → abstract behind a thin cache interface, default in-memory; Redis is a `.Redis` adapter.
- another product's BuildingBlocks → shared primitives live in `<House>.Kernel`, replicated, not referenced from haworks/Tie.
- audit/current-user singletons → ship `Null*` defaults; consumer overrides via `.WithAuditProvider(...)`.

### 2.5 Versioning & feed
- SemVer per package; `.Abstractions` versions independently and breaks rarely.
- Published to a **local NuGet feed** (a folder feed or a self-hosted BaGet/private feed). Consuming project adds the feed and `<PackageReference>`s the version it pins.

### 2.6 Definition of Done (a module is "packaged" only when)
1. Builds standalone in a fresh solution with **no reference to haworks/Tie** code.
2. Runs in a **bare sample consumer** (a minimal API that calls `AddXxx()` and exercises the surface) with **zero external infra**.
3. `.Abstractions` contains every type a consumer touches; no consumer needs the impl package's internals.
4. Tests green (ported + the module's own); analyzer green (no `NotImplementedException` in production — ported from `the-introduction-exchange/dotnet/src/Analyzers/`).
5. README: config schema, required consumer-supplied services, the `AddXxx()`/`.WithX()` surface, and a copy-paste composition snippet.

---

## 3. Module catalogue

| Module | Packages | Donor source | Founder-fenced? |
|--------|----------|--------------|------------------|
| **`<House>.Kernel`** | base | both donors' BuildingBlocks/SharedKernel | no |
| **`<House>.Identity`** | + `.Vault`, `.Messaging` | haworks `src/Identity/**` (token infra) **+** intro-exchange compliance gates | **YES** |
| **`<House>.Payments`** | + `.Stripe` | haworks `src/Payments/**` (Stripe Checkout + webhook) | **YES** |
| **`<House>.SecureDelivery`** | + `.Aws` | haworks `src/Media/**` (S3 presigned + access control + ClamAV) | no (review) |
| **`<House>.Entitlements`** | base | **net-new** (the keystone) — order-paid → entitlement → download | **YES** (money transitions) |
| **`<House>.Catalog`** | base | haworks `src/Catalog/**` (+ `ProductType` discriminator) | no |
| **`<House>.Notifications`** | + `.SendGrid`, `.Ses` | haworks `src/Notifications/**` (templated, idempotent email) | no |
| **`<House>.Engineering`** | analyzers + template | intro-exchange `Analyzers/`, PR template, war-room/deploy-log/status discipline, Pact + Playwright patterns | no |

**`<House>.Kernel`** — `Money` (long pence + banker's rounding, from `the-introduction-exchange/dotnet/ENGINEERING_STANDARDS.md:7-13`), `Result<T>`/`Error`, strongly-typed Ids, clock abstraction, `AuditableEntity`, the in-process **outbox** primitive. Replaces both `Haworks.BuildingBlocks.*` and `Tie.SharedKernel` so no module references a donor's blocks.

**`<House>.Payments`** — port `StripeCheckoutSessionService.cs:34-100` (`mode=payment`, NOT Connect), `StripeSignatureValidator.cs:24-62` (HMAC-SHA256 + tolerance + idempotency), `StripeWebhookProcessor.cs`, `Payment.cs:1-166`. Public surface to confirm at extraction: `ICheckoutSessionService`, `IWebhookValidator`, `PaymentOptions`. MoR mode (Stripe Managed Payments primary / Paddle fallback) is a config switch on this module (carry the decision from `specs/stage6-storefront-platform.md` §7).

**`<House>.SecureDelivery`** — port `MediaFile.cs:21-157`, `S3Service.cs` (`GeneratePresignedGetUrl`, configurable expiry), `GetMediaUrl.cs:25-58` (access check), ClamAV scan. Public surface to confirm: `ISecureFileStore`, `IAccessPolicy`, presign options. Access bound to an entitlement (consumer-supplied policy), not a hardcoded OwnerId.

**`<House>.Entitlements`** (net-new keystone) — `Entitlement` + `PackAsset`/`AssetLink` entities; the transactional `OrderPaid → grant → outbox → issue presigned URLs` flow (designed in `stage6-storefront-platform.md` §5). Outbox not saga. Refund/dispute → revoke.

**`<House>.Engineering`** — packages the *practices*, not runtime code: the Roslyn analyzer (bans `NotImplementedException`, `TreatWarningsAsErrors`), the money-rail PR template, and a `dotnet new` **solution template** that scaffolds a new project already wired to the house feed + a sample composition. This is how "compose, don't rebuild" becomes a one-command start.

> For every haworks-sourced module except Identity, the public surface above is **asserted from the prior component recon and must be confirmed at extraction** (anti-assumption gate, AGENTS.md §8 Pillar 1) — do not invent an interface that the extraction hasn't shown.

---

## 4. Identity module — reconciled (the one you flagged)

Identity is the clearest case for "harvest from many": the two donors are **complementary**, not redundant. haworks brings the **token infrastructure**; intro-exchange brings the **compliance/governance gates** haworks lacks.

### 4.1 From haworks — token infrastructure (grounded, deep recon)
Already a clean module surface (`src/Identity/Identity.Application/Interfaces/`):
- `IJwtTokenService` — `GenerateTokenAsync`, `ValidateTokenAsync`, `GetTokenValidationParameters`, cookie helpers, `GenerateServiceTokenAsync`.
- `ITokenRevocationService` — `RevokeTokenAsync`, `IsTokenRevokedAsync` (JTI revocation; L1 memory + optional L2 distributed; DB `RevokedTokens` fallback).
- `IRefreshTokenService` / `IRefreshTokenRepository` — DB-stored refresh tokens (`identity` schema).
- `IJwtSigningKeyProvider` — RS256; **`ConfigJwtSigningKeyProvider` (config PEM, zero-infra default)** vs `RotatingJwtSigningKeyRing` (Vault, opt-in). JWKS at `/.well-known/jwks.json` (`Identity.Api/Controllers/JwksController.cs`).
- ASP.NET Core Identity base (`User : IdentityUser`, `AppIdentityDbContext : IdentityDbContext<User>`), OAuth Google/Microsoft/Facebook (conditional on config), refresh + revocation, PBKDF2.
- **MFA is stubbed** — `User.TwoFactorEnabled` is *read but not enforced* (`LoginCommand.cs:178`); no TOTP scaffolding, no `IUserTwoFactorService`, no challenge-token flow. **Enforcement is net-new work in the module** (required for admin — fenced).

### 4.2 From intro-exchange — compliance gates (confirm surfaces at extraction)
These the earlier recon established; their exact public shapes are to be confirmed during extraction (the deep dig was interrupted):
- **Email verification** (`ResendVerificationCommand.cs`) — magic-link verify before privileged actions.
- **ToS-version acceptance gate** (`Tie.Api/Endpoints/AccountEndpoints.cs:86-102`) — client echoes `TosVersion`; server rejects stale → blocks blind-accept of outdated terms.
- **KYC tiers** (`KycLevel` enum Unverified/Basic/Enhanced) — fund/threshold gates by level.
- **GDPR erasure** (`User.Anonymize()`) — null PII, retain GUID + records for financial recordkeeping.
- **Verification-method tracking** (`VerificationMethod` enum OAuth/Fallback) — disputes weighted by proof strength.
- **OIDC identity binding** (`LinkedInOidcService.cs`) + **name matching** (`NameMatcher.cs`) — generalise OIDC beyond LinkedIn; keep name-match as anti-throwaway-account guard. (Matchmaking-specific pieces — connector standing, proposal blind-submission, bridge accept — are **not** packaged.)

### 4.3 The packaged Identity module = infra + gates, preset for the consumer
Composition presets so a consumer picks its level:
```csharp
services.AddIdentityCore(configuration);   // JWT + refresh + revocation + OAuth, config-signed, no infra
services.AddIdentity(configuration)        // + email verify, ToS gate, GDPR erasure, MFA enforcement
        .WithVault()                       // opt-in key rotation
        .WithMessaging();                  // opt-in privacy-erasure events (else in-process job)
```

---

## 5. Composition examples

**~~The £30 store (consumer #1)~~ — SUPERSEDED (see reconciling note at top).** The store chose a delivering MoR (Paddle), so it composes **none** of these modules — Paddle hosts payments, tax, delivery, accounts, and email. The store now needs only a Catalog + a Next.js shop window + an EngineBridge + an audit webhook (`specs/stage6-storefront-platform.md`). The composition below is kept only as an illustration of what a *first-party* (non-MoR) store would have looked like:
```
AddIdentity + AddCatalog + AddPayments(.WithStripe, MoR) + AddEntitlements
  + AddSecureDelivery(.WithAws) + AddNotifications(.WithSendGrid)
  + the app's own EngineBridge (Prospector PASS → Catalog product + upload pack files)
```

**A future project (e.g. a paid-newsletter or a course seller):** composes `Identity + Catalog + Payments + Entitlements + SecureDelivery + Notifications`, skips EngineBridge, writes its own domain. Zero auth/payments/delivery rebuild.

---

## 6. Decoupling backlog (the actual extraction work)

The recon shows the modules are ~60% drop-in; the gap is infra coupling. The packaging work *is* removing it:

1. **Identity** — extract `<House>.Identity.Abstractions`; make **Vault** a `.Vault` adapter (`ConfigJwtSigningKeyProvider` is already the zero-infra default — promote it); move **MassTransit** consumers (`PrivacyErasureRequestedConsumer`, `JwtKeyRotatedConsumer`) to `.Messaging` (in-process job by default); replace `Haworks.BuildingBlocks.*` inheritance (`AuditableEntity`, audit, current-user, cache) with `<House>.Kernel` + `Null*` defaults; ship `AddIdentityCore/AddIdentity/.WithVault/.WithMessaging` presets; **add real MFA** (TOTP + challenge-token flow — net-new, fenced).
2. **Payments** — drop MassTransit/saga coupling; webhook → in-process handler + outbox; confirm `ICheckoutSessionService`/`IWebhookValidator` surface.
3. **SecureDelivery** — drop module coupling; parameterise the access policy (entitlement-based).
4. **Kernel** — define once, so nothing references a donor's blocks.
5. **Notifications** — providers (SendGrid/SES) become `.SendGrid`/`.Ses` adapters behind `IEmailSender`.

Each item ends at the §2.6 Definition of Done.

---

## 7. Build sequence

1. **`<House>.Kernel`** (unblocks everything else; smallest).
2. **`<House>.Engineering`** (analyzer + solution template — so every later module scaffolds clean).
3. **`<House>.Identity`** (highest value, fenced; do the decoupling + MFA here). *(Claude)*
4. **`<House>.SecureDelivery`** + **`<House>.Catalog`** (parallel; not fenced). *(delegate, review)*
5. **`<House>.Payments`** (fenced) + **`<House>.Notifications`**. *(Payments → Claude)*
6. **`<House>.Entitlements`** (fenced design; keystone). *(Claude design, delegate non-money)*
7. **Compose consumer #1** = the store (`specs/stage6-storefront-platform.md`), now just references + glue.

Each module gates on its Definition of Done (§2.6) before the next depends on it.

---

## 8. Founder fence

- **Claude (manager + fenced impl):** `<House>.Identity` (incl. MFA), `<House>.Payments` (Stripe/MoR), `<House>.Entitlements` money transitions, `<House>.Kernel.Money`. Specs + review for all else.
- **Delegate:** `<House>.Kernel` (non-money), `.SecureDelivery`, `.Catalog`, `.Notifications`, `.Engineering`, the sample consumers — against this spec, money/identity untouched.

---

## 9. Open questions (don't block writing; settle before §7 step 1)

1. **House namespace + feed name.** Modules must be product-neutral (drop into *any* project), so not `Haworks.*`/`Tie.*`. Recommend a neutral house name (placeholder `<House>` throughout). **Decision needed before Kernel.**
2. **Feed mechanism.** Local folder feed vs self-hosted private feed (BaGet). Default: local folder feed (simplest, honours local-first).
3. **DbContext model.** Module-owns-DbContext (default) vs compose-into-shared. Default (a); document (b).
4. **MFA factor.** TOTP (authenticator app) vs email-code for admin. Default: TOTP.

---

*Invariant check (AGENTS.md §2): packaging changes no truth rule. The modules are infrastructure; the engine's moat, source-or-die, verdict-from-retrieval, and publish-only-on-PASS are untouched and live in the Prospector engine, not in this library. A module is "done" only when it builds with zero donor coupling and a bare consumer exercises it — asserted surfaces are confirmed at extraction, never invented.*
