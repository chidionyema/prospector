namespace Store.Api.Contracts;

/// <summary>
/// Contract for PATCH /internal/catalog/{id}/price — move a pack's price, touching nothing else.
///
/// Same narrow-door rationale as the facet, listing and content patches: /internal/catalog is an
/// upsert that assigns ProviderProductId, ProviderPriceId and DossierRef unconditionally, so a
/// caller who wanted only to re-price a pack would rewrite its money rail as a side effect. It
/// also, as it happens, ignores PricePence entirely on the update path — so before this endpoint
/// existed there was no way to re-price a published pack at all.
///
/// The provider Price is minted by the caller (the engine already does this in bridge.py) rather
/// than here, so that Stripe object creation stays in one place and stays idempotent on
/// (product, amount, currency). This endpoint's job is to refuse anything the provider cannot
/// actually bill, and to move the catalogue and the fulfilment floor together.
/// </summary>
/// <param name="PricePence">The new price new checkout sessions will mint at.</param>
/// <param name="ProviderPriceId">
/// The provider Price object new sessions mint from. Stripe Price objects are immutable, so a
/// change means a NEW id; it is verified billable before anything is committed. Omit only when
/// re-pricing a pack that is not currently sellable.
/// </param>
/// <param name="Reason">
/// Why, in one line, recorded on the history row. Required: a price that moved with no stated
/// cause is indistinguishable from a bug, and the next person to look will move it back.
/// </param>
/// <param name="Actor">Who or what applied it — e.g. "price-engine", "founder". Required.</param>
/// <param name="RationaleRef">
/// Optional pointer to the engine-side derivation record (inputs, steps, cited comparables).
/// </param>
public record PricePatchRequest(
    long PricePence,
    string? ProviderPriceId,
    string Reason,
    string Actor,
    string? RationaleRef = null,
    /// <summary>
    /// The same rung in US cents, for buyers billed in USD (founder decision 2026-08-14).
    /// Appended last so every existing caller keeps compiling and keeps its behaviour.
    ///
    /// OMITTED MEANS UNCHANGED, never cleared. A GBP-only caller must not be able to strip USD
    /// billability off a pack by not mentioning it — that would take a US buyer's ability to
    /// purchase away as a side effect of an unrelated price move.
    /// </summary>
    long? PriceUsdCents = null);
