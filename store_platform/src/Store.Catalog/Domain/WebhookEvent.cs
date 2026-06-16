namespace Store.Catalog.Domain;

public sealed class WebhookEvent
{
    public long Id { get; set; }
    public required string Provider { get; set; }
    public required string ProviderEventId { get; set; }
    public required string EventType { get; set; }
    public required string RawPayload { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}
