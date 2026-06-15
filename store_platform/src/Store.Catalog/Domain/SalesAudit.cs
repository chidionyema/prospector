namespace Store.Catalog.Domain;

public class SalesAudit
{
    public long Id { get; set; }
    public required string PaddleTransactionId { get; set; }
    public required string PaddleProductId { get; set; }
    public long AmountPence { get; set; }
    public required string Currency { get; set; }
    public required string Country { get; set; }
    public DateTime OccurredAt { get; set; }
}
