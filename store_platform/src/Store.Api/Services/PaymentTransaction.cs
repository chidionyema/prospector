namespace Store.Api.Services;

/// <summary>Provider-agnostic view of a completed payment, parsed from the webhook body.</summary>
public sealed record PaymentTransaction(
    string Provider,
    string TransactionId,
    string BuyerEmail,
    string Currency,
    string Country,
    long TotalAmountPence,
    DateTime OccurredAt,
    IReadOnlyList<PurchasedItem> Items,

    /// <summary>
    /// The id that came back off the provider's session metadata, or null.
    /// </summary>
    /// <remarks>
    /// Trailing and defaulted so every existing construction site still compiles, and so a
    /// session created before this shipped parses to null rather than throwing. Null is a
    /// normal answer, not a fault: it means the checkout predates this, or came from a client
    /// that sent no header.
    /// </remarks>
    string? CorrelationId = null);
