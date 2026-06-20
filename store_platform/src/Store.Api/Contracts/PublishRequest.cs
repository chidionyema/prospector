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
    // Legacy fields — accepted for backward compatibility when the provider-agnostic
    // fields above are not present.
    string? PaddleProductId = null,
    string? PaddlePriceId = null
);
