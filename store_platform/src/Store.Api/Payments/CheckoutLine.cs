namespace Store.Api.Payments;

/// <summary>
/// One pack in a checkout. A checkout carries a list of these rather than a single pack so a
/// buyer can pay for several packs in one transaction — the fulfilment side has always been
/// multi-item (see <see cref="Store.Catalog.Domain.Order"/> and FulfilmentService's item loop);
/// only the entrance was single-pack.
/// </summary>
/// <param name="PackId">
/// The catalogue id. Stamped into checkout-session metadata so the inbound webhook can resolve
/// WHICH packs were bought and grant the right entitlements.
/// </param>
/// <param name="ProviderPriceId">The provider's price object for that pack.</param>
/// <param name="Currency">
/// The ISO-4217 currency the buyer is billed in, resolved SERVER-SIDE from the request (see
/// <c>CheckoutEndpoints.ResolveBuyerCurrency</c>). Appended last with a "GBP" default so every
/// existing construction site — and every provider that sells in one currency — keeps compiling
/// and keeps today's behaviour.
///
/// It rides on the LINE rather than on the session signature for two reasons: the alternative was
/// a new parameter on three interface methods and their three implementations, and the value has
/// to survive <see cref="SmokeTestPricing"/>'s <c>with</c>-rewrite of the price id, which copies
/// the record. A checkout is nonetheless billed in exactly ONE currency —
/// <c>StripeProvider.BuildSessionOptions</c> refuses a lines list carrying more than one rather
/// than silently billing everything in the first line's.
/// </param>
public sealed record CheckoutLine(string PackId, string ProviderPriceId, string Currency = "GBP");
