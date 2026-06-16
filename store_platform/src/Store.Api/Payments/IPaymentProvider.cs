namespace Store.Api.Payments;

using Store.Api.Services;

public interface IPaymentProvider
{
    string Name { get; } // "paddle"

    // Inbound: verify signature + parse body into the provider-agnostic transaction.
    Task<WebhookVerifyResult> VerifyAndParseAsync(HttpRequest request, string rawBody, IConfiguration config, ILogger logger);

    // Outbound (provisioning/checkout) — NOT used by Paddle in P0 (bridge.py provisions Paddle,
    // and Paddle checkout is a frontend overlay). Implement as NotSupported for now; Stripe fills
    // these in P2/P3.
    Task<ProviderProduct> CreateProductAsync(string title, long pricePence, string currency, IDictionary<string,string> metadata, CancellationToken ct);
    Task<CheckoutHandle> CreateCheckoutAsync(string providerPriceId, string? buyerEmail, string successUrl, string cancelUrl, CancellationToken ct);
}
