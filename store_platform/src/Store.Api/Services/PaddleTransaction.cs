namespace Store.Api.Services;

/// <summary>Provider-agnostic view of a completed payment, parsed from the webhook body.</summary>
public sealed record PaddleTransaction(
    string TransactionId,
    string BuyerEmail,
    string Currency,
    string Country,
    long TotalAmountPence,
    DateTime OccurredAt,
    IReadOnlyList<PurchasedItem> Items);
