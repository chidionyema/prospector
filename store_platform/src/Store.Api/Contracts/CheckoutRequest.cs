namespace Store.Api.Contracts;

/// <summary>
/// Buyer checkout request body. The email is optional — Stripe Checkout can
/// collect it on the hosted page; Paddle overlay handles it client-side.
/// </summary>
/// <param name="Email">Optional; the provider collects it otherwise.</param>
/// <param name="Embedded">
/// Ask for a session that renders inside the storefront instead of on the provider's domain.
/// A request, not a demand: the server answers with the hosted URL whenever the provider has no
/// embedded surface, so an old client and a provider without embedded support both keep working.
/// Defaults to false, which is exactly the behaviour that existed before this field.
/// </param>
public record CheckoutRequest(string? Email = null, bool Embedded = false);
