namespace Store.Api.Contracts;

public record PublishRequest(
    string Id,
    string Title,
    string OneLine,
    string DossierRef,
    string? PaddleProductId = null,
    string? PaddlePriceId = null,
    bool IsListed = false,
    long? PricePence = null
);
