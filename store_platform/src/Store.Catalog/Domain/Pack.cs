namespace Store.Catalog.Domain;

public class Pack
{
    public required string Id { get; set; }
    public required string Title { get; set; }
    public required string OneLine { get; set; }
    public long PricePence { get; set; }
    public string PaymentProvider { get; set; } = "paddle";
    public string? ProviderProductId { get; set; }
    public string? ProviderPriceId { get; set; }
    public bool IsListed { get; set; }
    public required string DossierRef { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    // Deliverable content (the purchased ZIP) in object storage. A pack must never be
    // listed (IsListed=true) unless ContentKey is set — selling something undeliverable
    // is the cardinal sin of this layer. ContentVersion bumps on each republish so
    // existing entitlements can pin the version they bought.
    public string? ContentKey { get; set; }
    public string? ContentHash { get; set; }
    public int ContentVersion { get; set; } = 1;

    // Storefront conversion metadata, set by the engine at publish time from the verified
    // dossier. All optional — a pack lists without them. Arrays and the financial snapshot
    // are stored as JSON text and re-hydrated by the read API (SQLite has no array column).
    public string? Headline { get; set; }
    public string? Subhead { get; set; }
    public string? ProofPoint { get; set; }
    public string? WhoPays { get; set; }
    public string? EffortTag { get; set; }
    public string? TimeToFirstRevenue { get; set; }
    public string? QaVerdictSummary { get; set; }
    public int? SourceCount { get; set; }
    public DateTime? VerifiedAt { get; set; }
    public string? WhatYouGetJson { get; set; }
    public string? SampleExtractJson { get; set; }
    public string? FinancialSnapshotJson { get; set; }
}
