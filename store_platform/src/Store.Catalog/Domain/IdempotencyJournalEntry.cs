namespace Store.Catalog.Domain;

public sealed class IdempotencyJournalEntry
{
    public required string IdempotencyKey { get; set; } // PK
    public required string CommandType { get; set; }
    public required string Status { get; set; } // "InProgress" | "Completed"
    public string? RequestFingerprint { get; set; }
    public int? StatusCode { get; set; }
    public string? ContentType { get; set; }
    public string? ResponseBodyBase64 { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime ExpiresAt { get; set; }

    public const string StatusInProgress = "InProgress";
    public const string StatusCompleted = "Completed";
}
