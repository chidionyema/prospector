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

    // The jurisdiction the OPPORTUNITY is in ("uk", "us", "us-tx"), not the buyer's
    // locale. A US-market pack is still sold in GBP through the existing rail; this is a
    // browse/filter facet and a disclosure, never a pricing or tax input. Null on every
    // pack published before the engine had a market dimension.
    public string? Market { get; set; }

    // Discovery facets — the closed vocabulary in PackFacets, emitted by the engine from a
    // verified dossier and validated at the publish boundary. All nullable on purpose: an
    // untagged pack lists under "All" and never under a specific value. Nothing here may be
    // inferred from pack text (that is what the deleted browser-side sector regex did, and
    // it labelled a metal fabricator a gardening business in public).
    public string? Sector { get; set; }
    public string? Payer { get; set; }
    public string? Effort { get; set; }
    public string? Commitment { get; set; }
    public string? Mechanism { get; set; }

    // Multi-valued (0-3 of PackFacets.Advantage) stored as JSON text — SQLite has no array
    // column, same convention as WhatYouGetJson above.
    public string? AdvantagesJson { get; set; }
}
