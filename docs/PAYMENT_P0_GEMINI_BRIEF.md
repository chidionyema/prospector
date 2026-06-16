# Gemini Implementation Brief — P0: Payment-provider seam (zero behavior change)

**Repo:** `/Users/chidionyema/Documents/code/prospector` · **Project:** `store_platform/src/` (.NET 9)
**Parent spec:** `docs/PAYMENT_RAIL_INDEPENDENCE_SPEC.md` (§4, §9 P0). Read it first.
**Reviewer:** Claude reviews the full diff + runs build/tests before commit. Do NOT commit yourself.

## Goal
Introduce a provider abstraction (`IPaymentProvider`) and route webhooks generically, **without
changing any runtime behavior**. After P0, the live Paddle webhook path must behave **byte-identically**
to today. This is a refactor only. **Do NOT** rename any database column or touch any EF entity /
migration — that is P1, explicitly out of scope here.

## Absolute constraints
1. **Zero behavior change.** Same signature verification, same JSON parsing, same fulfilment, same
   email dispatch, same HTTP responses. If a test changes meaning, you did it wrong.
2. **Do NOT touch** `Store.Catalog/Domain/*` (Pack, Order, SalesAudit), `Persistence/StoreDbContext.cs`,
   or `Migrations/*`. The domain columns stay named `Paddle*` until P1.
3. **No new NuGet packages.** No Stripe code in P0.
4. All existing tests must pass unchanged. `dotnet build` clean (treat warnings as you find them —
   do not introduce new ones).
5. Secrets stay in config/env; never hardcode. Repo is public.

## Current code (the two files that matter)
- `store_platform/src/Store.Api/Services/PaddleTransaction.cs` — a record documented
  *"Provider-agnostic view of a completed payment"*. Fields: `TransactionId, BuyerEmail, Currency,
  Country, TotalAmountPence, OccurredAt, Items` (+ `PurchasedItem(ProductId, AmountPence)` in
  `PurchasedItem.cs`).
- `store_platform/src/Store.Api/Endpoints/WebhookEndpoints.cs` — maps `POST /webhooks/paddle`,
  reads `Paddle:WebhookSecret`, verifies `Paddle-Signature` (`VerifyPaddleSignature`, HMAC-SHA256,
  ±5 min), parses JSON (`ParsePaddleTransaction` + helpers `ExtractEmail/ExtractCountry/
  ParseOccurredAt/ParseAmount/OptionalString`), then calls `FulfilmentService.FulfilAsync(txn)` and
  `DispatchEmailsAsync`.
- `FulfilmentService.cs` consumes the record type — it will need the type **rename** applied but no
  logic change.

## Steps

### 1. Rename the record (provider-agnostic) + add `Provider`
- Rename file `Services/PaddleTransaction.cs` → `Services/PaymentTransaction.cs`; rename the record
  `PaddleTransaction` → `PaymentTransaction`; **add a leading field** `string Provider` (the source
  rail, e.g. `"paddle"`). Keep all other fields identical.
- Update every reference (`FulfilmentService.cs`: `FulfilAsync`, `FulfilItemAsync`, `CommitAsync`,
  `BuildAudit`, `NewOrder` signatures/locals; `WebhookEndpoints.cs`). `FulfilmentService` logic is
  unchanged — it just takes `PaymentTransaction` now. It does **not** read `Provider` in P0.

### 2. Define the provider seam — `Store.Api/Payments/IPaymentProvider.cs` (new)
```csharp
namespace Store.Api.Payments;

public interface IPaymentProvider
{
    string Name { get; } // "paddle"

    // Inbound: verify signature + parse body into the provider-agnostic transaction.
    Task<WebhookVerifyResult> VerifyAndParseAsync(HttpRequest request, string rawBody, IConfiguration config, ILogger logger);

    // Outbound (provisioning/checkout) — NOT used by Paddle in P0 (bridge.py provisions Paddle,
    // and Paddle checkout is a frontend overlay). Implement as NotSupported for now; Stripe fills
    // these in P2/P3.
    Task<ProviderProduct> CreateProductAsync(string title, long pricePence, string currency, IDictionary<string,string> metadata, CancellationToken ct);
    Task<CheckoutHandle> CreateCheckoutAsync(string providerPriceId, string? buyerEmail, string successUrl, string cancelUrl, CancellationToken ct);
}

public sealed record WebhookVerifyResult(bool Verified, Store.Api.Services.PaymentTransaction? Transaction, string? Reason, bool Ignored = false);
public sealed record ProviderProduct(string ProviderProductId, string ProviderPriceId);
public sealed record CheckoutHandle(string Url, string? ClientSecret);
```
- `WebhookVerifyResult.Ignored` lets a provider say "valid but not a `transaction.completed` event"
  (today's `IGNORED` branch) distinctly from a verify failure.

### 3. `Store.Api/Payments/PaddleProvider.cs` (new) — move Paddle logic here verbatim
- Implement `IPaymentProvider` with `Name => "paddle"`.
- **Move** (cut, don't rewrite) from `WebhookEndpoints.cs` into this class: `VerifyPaddleSignature`,
  `ParsePaddleTransaction`, `ExtractEmail`, `ExtractCountry`, `ParseOccurredAt`, `ParseAmount`,
  `OptionalString`, and the `SignatureToleranceMinutes` const.
- `VerifyAndParseAsync`: reproduce today's HandlePaddleWebhook+ProcessAsync front half exactly:
  - missing/empty `Paddle:WebhookSecret` → `WebhookVerifyResult(false, null, "secret-not-configured")`
    (caller maps to **503**, as today — keep that status).
  - missing `Paddle-Signature` header → `(false, null, "missing-signature")` → **400**.
  - signature invalid → `(false, null, "invalid-signature")` → **400**.
  - malformed JSON → `(false, null, "malformed")` → **400**.
  - `event_type != "transaction.completed"` → `(false, null, eventType, Ignored: true)` → caller
    returns today's `Ok({status="IGNORED", eventType})`.
  - success → `(true, ParsePaddleTransaction(root) with Provider="paddle", null)`.
- `CreateProductAsync`/`CreateCheckoutAsync` → `throw new NotSupportedException("Paddle provisioning
  is handled by the Python bridge; Paddle checkout is a frontend overlay.")`.

### 4. Rewrite `WebhookEndpoints.cs` to route generically
- Map **both**: `app.MapPost("/webhooks/{provider}", HandleWebhook)` **and keep**
  `app.MapPost("/webhooks/paddle", ...)` as a permanent explicit alias that resolves provider
  `"paddle"` (so existing Paddle config keeps working even if {provider} routing has a gap).
- `HandleWebhook(string provider, ...)`: resolve `IPaymentProvider` from keyed DI by `provider`
  (`sp.GetKeyedService<IPaymentProvider>(provider)`); unknown provider → **404**.
  Read raw body, call `VerifyAndParseAsync`, then map results to the **same** HTTP responses/branches
  ProcessAsync produces today (503/400/IGNORED/PROCESSED/ALREADY_PROCESSED), and on success call the
  **unchanged** `FulfilmentService.FulfilAsync` + `DispatchEmailsAsync`. Keep `DispatchEmailsAsync`
  where it is (it is provider-agnostic).

### 5. `Store.Api/Payments/MoneyRailConfigGate.cs` (new) — boot-time fail-closed
- Minimal validator run at startup (e.g. an `IHostedService` `StartAsync` or inline in Program.cs
  before `app.Run()`): read `payments:active_provider` (default `"paddle"`). For the active provider,
  assert its required secret is present (Paddle → `Paddle:WebhookSecret`). If missing, **throw** so
  the app refuses to start (log a clear message). Do not validate disabled providers.
- Keep it tiny; it is the seam for richer checks (live/test key isolation) when Stripe lands.

### 6. DI registration — `Program.cs`
- `builder.Services.AddKeyedScoped<IPaymentProvider, PaddleProvider>("paddle");`
- Wire `MoneyRailConfigGate` (hosted service or explicit call). Nothing else changes.

## Acceptance criteria (Claude verifies all of these)
1. `dotnet build store_platform/src/Store.Api` (and the solution) — clean, no new warnings.
2. `dotnet test` for `Store.Tests` — **all green, unchanged** (esp. `Fulfilment/FulfilmentServiceTests.cs`).
3. `POST /webhooks/paddle` behavior is byte-identical: valid signed `transaction.completed` →
   fulfilment + 200 `PROCESSED`; bad signature → 400; missing secret → 503; non-completed event →
   200 `IGNORED`; duplicate → `ALREADY_PROCESSED`. Add/keep tests proving the verify+parse moved
   into `PaddleProvider` without changing outcomes.
4. `POST /webhooks/{provider}` with an unknown provider → 404; with `paddle` → identical to the alias.
5. App refuses to start if `Paddle:WebhookSecret` is absent while paddle is the active provider.
6. **No** change to `Store.Catalog/Domain/*`, `StoreDbContext`, or `Migrations/*`.

## Out of scope (do NOT do in P0)
- Renaming DB columns / EF migration (that's **P1**).
- Any Stripe code (**P2+**).
- Hot-reload `active_provider` / auto-failover (**P7**).
- Python `bridge.py` changes (**P3**).

## Deliverable to reviewer
A single diff touching only: `Services/PaymentTransaction.cs` (renamed), `Services/FulfilmentService.cs`
(type rename only), `Endpoints/WebhookEndpoints.cs` (generic routing), new `Payments/IPaymentProvider.cs`,
`Payments/PaddleProvider.cs`, `Payments/MoneyRailConfigGate.cs`, `Program.cs` (DI), and test
additions/renames under `Store.Tests`. Plus the output of `dotnet build` + `dotnet test`.
