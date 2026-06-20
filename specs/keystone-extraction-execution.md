# Keystone Kernel — Execution Spec

**Goal:** Execute PLATFORM_KERNEL_PLAN.md in order. Every step independently shippable.
**Founder fence:** Identity + money + contracts + migrations stay on Claude.
**Verify command:** `dotnet test` (haworks-platform) / `dotnet build` (keystone) / `.venv/bin/python -m pytest -q` (prospector).

---

## Phase 0 — Step-0 fixes in haworks-platform (BLOCKING)

### Fix 0.1: SagaPersistenceInterceptor — make opt-in
**File:** `src/BuildingBlocks/Extensions/ServiceDefaults.cs`
**Line 80:** Remove the global registration:
```csharp
builder.Services.AddSingleton<ISaveChangesInterceptor, SagaPersistenceInterceptor>();
```
The opt-in already exists in `MessagingServiceCollectionExtensions.cs:58`. No new method needed — just delete the line. Services that need saga auditing call `AddMassTransitObservability()` or register manually.

### Fix 0.2: Dual Polly stacks — keep v8 only
**Problem:** `ServiceDefaults.cs` applies `AddStandardResilienceHandler()` (Polly v8 native pipeline) globally to all HttpClient defaults. Separately, `ResiliencePolicyFactory` creates v7-compat policies that 12 Stripe/PayPal services manually wrap around their calls. Result: double-retry, double-circuit-breaker.

**Fix:**
1. Delete `src/BuildingBlocks/Resilience/ResiliencePolicyFactory.cs`
2. Delete `src/BuildingBlocks/Resilience/IResiliencePolicyFactory.cs` (ResilienceOptions + BulkheadOptions stay in the file, rename it to `ResilienceOptions.cs`)
3. Delete fallback handlers: `src/BuildingBlocks/Resilience/Fallbacks/NullFallbackHandler.cs`, `src/BuildingBlocks/Resilience/Fallbacks/CriticalOperationHandler.cs`
4. Delete `src/BuildingBlocks/Resilience/IResilienceMetrics.cs` and `NullResilienceMetrics` if they exist only for the factory
5. Migrate the 12 usage sites in `src/Payments/Payments.Infrastructure/` to use v8 `ResiliencePipelineRegistry` or remove manual wrapping entirely (they already get `AddStandardResilienceHandler` from the global defaults)
6. Check `src/BuildingBlocks/Vault/VaultService.cs` and `VaultAppRoleAuthenticator.cs` — they use Polly directly (not via the factory). If they use v7 API, migrate to v8.

**Acceptance:** `dotnet build` passes for all .sln files. No references to `ResiliencePolicyFactory`, `IResiliencePolicyFactory`, `NullFallbackHandler`, `CriticalOperationHandler`.

### Fix 0.3: Error.cs domain constants — move to domains
**File:** `src/BuildingBlocks/Common/Error.cs`
**Fix:** Move each `Error.X` static class into its respective domain project:
- `Error.Payment` → `src/Payments/Payments.Domain/Errors/PaymentErrors.cs`
- `Error.Auth` → `src/Identity/Identity.Domain/Errors/AuthErrors.cs`
- `Error.Vault` → `src/BuildingBlocks/Vault/VaultErrors.cs` (Vault is a building block, keep local)
- `Error.Content` → `src/Media/Media.Domain/Errors/ContentErrors.cs`
- `Error.Orders` → `src/Orders/Orders.Domain/Errors/OrderErrors.cs`
- `Error.Reviews` → `src/Catalog/Catalog.Domain/Errors/ReviewErrors.cs` (or move Reviews to its own domain)
- `Error.Categories` → `src/Catalog/Catalog.Domain/Errors/CategoryErrors.cs`
- `Error.Products` → `src/Catalog/Catalog.Domain/Errors/ProductErrors.cs`
- `Error.Users` → `src/Identity/Identity.Domain/Errors/UserErrors.cs`
- `Error.Checkout` → `src/CheckoutOrchestrator/CheckoutOrchestrator.Domain/Errors/CheckoutErrors.cs`
- `Error.Subscription` → `src/Payments/Payments.Domain/Errors/SubscriptionErrors.cs`
- `Error.ValidationErrors` — keep in BuildingBlocks (truly shared)

Update all 45+ usages across the codebase to reference the new locations.

**Acceptance:** `dotnet build` passes for all .sln files. `Error.cs` contains only `ErrorType`, the base `Error` record, factory methods (Validation, NotFound, Storage, Database, Internal, Timeout, Forbidden, Conflict), and `ValidationErrors`.

### Fix 0.4: HangfireJobId — no code change
Just don't extract Scheduler. Confirmed: `ScheduledEvent` has `HangfireJobId` property — it's infra leaking into domain. Not fixable cleanly; the package simply won't be part of the kernel.

---

## Phase 1 — Create Keystone repo + core packages

### 1.1: Create repo `chidionyema/keystone` (GitHub)
Create under `~/Documents/code/keystone/`. Structure:
```
keystone/
  Directory.Build.props
  Directory.Packages.props
  keystone.sln
  src/
    Keystone.Kernel/
    Keystone.Observability/
    Keystone.Resilience/
    Keystone.Idempotency/
  tests/
    Keystone.Kernel.Tests/
    Keystone.Observability.Tests/
    Keystone.Resilience.Tests/
    Keystone.Idempotency.Tests/
```

### 1.2-1.5: Extract each core package
Follow PLATFORM_KERNEL_PLAN.md §2 source/strip instructions. Details in plan.

---

## Phase 2-6 — Capability + founder-fence packages
Per PLATFORM_KERNEL_PLAN.md §5 extraction order.
