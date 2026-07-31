namespace Store.Api.Contracts;

/// <summary>
/// Contract for PATCH /internal/catalog/{id}/listing — withdraw a pack from sale, or put a
/// withdrawn one back, without touching anything else about it.
///
/// This exists because the only way to change listing state used to be re-POSTing the whole
/// pack to /internal/catalog, and that upsert assigns ProviderProductId, ProviderPriceId and
/// DossierRef unconditionally. A caller who wanted to pull one pack off sale and did not
/// happen to know its Stripe ids would silently wipe them — the money rail destroyed by a
/// moderation action. So "stop selling this" needs its own door.
/// </summary>
/// <param name="IsListed">false withdraws the pack from the catalogue; true restores it.</param>
/// <param name="Reason">
/// Why, in one line, recorded on the pack. Required: a pack vanishing from the storefront with
/// no stated cause is indistinguishable from a bug, and the next person to look will re-list it.
/// </param>
public record ListingPatchRequest(bool IsListed, string Reason);
