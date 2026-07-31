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
public sealed record CheckoutLine(string PackId, string ProviderPriceId);
