namespace Store.Api.Payments;

/// <summary>
/// A provider-agnostic money-reversal signal (refund or chargeback/dispute). Unlike a
/// <see cref="Services.PaymentTransaction"/>, a reversal grants nothing — it REVOKES the
/// entitlement(s) previously granted for the original payment so a refunded/disputed buyer
/// can no longer download. <see cref="OriginalTransactionId"/> is the id of the original
/// payment (Stripe PaymentIntent / Paddle transaction) and matches
/// <c>Order.ProviderTransactionId</c> / <c>SalesAudit.ProviderTransactionId</c>.
/// <see cref="ReversalEventId"/> is the reversal event's own id, used for webhook dedup.
/// </summary>
public sealed record PaymentReversal(
    string Provider,
    string ReversalEventId,
    string OriginalTransactionId,
    string Kind); // "refund" | "dispute"
