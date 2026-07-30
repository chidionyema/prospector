namespace Store.Api.Contracts;

/// <summary>
/// Contract for the engine→store publish call (POST /internal/catalog).
/// For backward compatibility, the legacy fields (PaddleProductId, PaddlePriceId)
/// are accepted as fallbacks when the provider-agnostic fields are absent.
/// </summary>
public record PublishRequest(
    string Id,
    string Title,
    string OneLine,
    string DossierRef,
    string? PaymentProvider = null,
    string? ProviderProductId = null,
    string? ProviderPriceId = null,
    bool IsListed = false,
    long? PricePence = null,
    string? ContentKey = null,
    string? ContentHash = null,
    int? ContentVersion = null,
    // Storefront conversion metadata — the per-pack specifics the engine derives from the
    // verified dossier so the catalogue can sell each pack on its own merits rather than
    // generic boilerplate. All optional and additive: a pack still lists without them.
    string? Headline = null,
    string? Subhead = null,
    string? ProofPoint = null,
    string? WhoPays = null,
    string? EffortTag = null,
    string? TimeToFirstRevenue = null,
    string? QaVerdictSummary = null,
    int? SourceCount = null,
    DateTime? VerifiedAt = null,
    string[]? WhatYouGet = null,
    string[]? SampleExtract = null,
    IReadOnlyDictionary<string, string>? FinancialSnapshot = null,
    // Jurisdiction of the opportunity ("uk", "us", "us-tx"). Independent of the currency
    // the pack sells in — the store stays GBP-only.
    string? Market = null,
    // Legacy fields — accepted for backward compatibility when the provider-agnostic
    // fields above are not present.
    string? PaddleProductId = null,
    string? PaddlePriceId = null,
    // Discovery facets (closed vocabulary — Store.Catalog.Domain.PackFacets). Appended at the
    // end because positional record parameters are append-only for back-compat: existing
    // callers such as Store.Tests/Domain/PackMarketTests.cs:29-31, which construct
    // new PublishRequest("p1","T","O","d1"), must keep compiling unmodified.
    // An omitted facet stays null — the engine is instructed to omit what it cannot justify
    // rather than guess, and a publish carrying an unknown value is rejected with 400.
    string? Sector = null,
    string? Payer = null,
    string? Effort = null,
    string? Commitment = null,
    string? Mechanism = null,
    string[]? Advantages = null
);
