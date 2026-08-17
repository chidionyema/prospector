namespace Store.Api.Services;

/// <summary>One line item from a payment transaction: the provider product id and the
/// per-item amount in pence (best-effort; the authoritative total is on SalesAudit).</summary>
public sealed record PurchasedItem(string? ProductId, long AmountPence);
