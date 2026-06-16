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
    // Legacy fields — accepted for backward compatibility when the provider-agnostic
    // fields above are not present.
    string? PaddleProductId = null,
    string? PaddlePriceId = null
);
