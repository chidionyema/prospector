namespace Store.Api.Contracts;

/// <summary>
/// Basket checkout request body: several packs paid for in one transaction.
/// </summary>
/// <param name="PackIds">
/// Catalogue ids. Order is preserved into the provider session so the buyer sees the basket in
/// the order they built it. Duplicates are rejected rather than collapsed — a pack is a one-off
/// digital download, so asking for two of the same is a client bug, not an order for two.
/// </param>
/// <param name="Email">Optional; the provider collects it otherwise.</param>
/// <param name="Embedded">
/// Ask for a session that renders inside the storefront rather than on the provider's domain.
/// See <see cref="CheckoutRequest"/> — the server falls back to hosted whenever it cannot.
/// </param>
public record CartCheckoutRequest(string[]? PackIds = null, string? Email = null, bool Embedded = false);
