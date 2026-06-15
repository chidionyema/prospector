namespace Store.Catalog.Domain;

public class Pack
{
    public required string Id { get; set; }
    public required string Title { get; set; }
    public required string OneLine { get; set; }
    public long PricePence { get; set; }
    public string? PaddleProductId { get; set; }
    public string? PaddlePriceId { get; set; }
    public bool IsListed { get; set; }
    public required string DossierRef { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}
