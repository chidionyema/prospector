namespace Store.Catalog.Domain;

public class SalesAudit
{
    public long Id { get; set; }
    public string PaymentProvider { get; set; } = "paddle";
    public required string ProviderTransactionId { get; set; }
    public required string ProviderProductId { get; set; }
    public long AmountPence { get; set; }
    public required string Currency { get; set; }
    public required string Country { get; set; }
    public DateTime OccurredAt { get; set; }
}
