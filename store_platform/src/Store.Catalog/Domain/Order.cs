namespace Store.Catalog.Domain;

/// <summary>
/// A fulfilment record for one purchased pack. One Paddle transaction can produce
/// several Orders (multi-item cart). The authoritative financial total for the whole
/// transaction lives on <see cref="SalesAudit"/>; this row records what was bought
/// and drives entitlement. PackId is nullable to capture a paid-but-unfulfillable
/// sale (unknown product) without ever dropping the money on the floor.
/// </summary>
public class Order
{
    public long Id { get; set; }
    public required string PaddleTransactionId { get; set; }
    public string BuyerEmail { get; set; } = "";
    public string? PackId { get; set; }
    public long AmountPence { get; set; }
    public required string Currency { get; set; }
    public string Country { get; set; } = "";
    public OrderStatus Status { get; set; } = OrderStatus.Paid;
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}
