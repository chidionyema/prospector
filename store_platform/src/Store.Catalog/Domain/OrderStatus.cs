namespace Store.Catalog.Domain;

/// <summary>Lifecycle of a purchase. A sale starts Paid; refunds/disputes move it on.</summary>
public enum OrderStatus
{
    Paid = 0,
    Refunded = 1,
    PartiallyRefunded = 2,
    Disputed = 3
}
