namespace Store.Api.Contracts;

/// <summary>
/// Buyer checkout request body. The email is optional — Stripe Checkout can
/// collect it on the hosted page; Paddle overlay handles it client-side.
/// </summary>
public record CheckoutRequest(string? Email = null);
