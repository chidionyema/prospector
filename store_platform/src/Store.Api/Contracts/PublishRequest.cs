namespace Store.Api.Contracts;

public record PublishRequest(
    string Id,
    string Title,
    string OneLine,
    string DossierRef,
    string? PaddleProductId = null,
    string? PaddlePriceId = null,
    bool IsListed = false,
    long? PricePence = null,
    string? ContentKey = null,
    string? ContentHash = null,
    int? ContentVersion = null
);
