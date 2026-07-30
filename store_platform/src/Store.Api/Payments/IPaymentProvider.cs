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
    // packId is stamped into the checkout session metadata so the inbound webhook can
    // resolve WHICH pack was bought and grant the right entitlement. Without it, the
    // webhook's ExtractItems finds no pack_id and fulfilment grants nothing (paid-but-
    // unfulfilled). See P0-1 in docs/PIPELINE_REVIEW_2026-06-18.md.
    Task<CheckoutHandle> CreateCheckoutAsync(string packId, string providerPriceId, string? buyerEmail, string successUrl, string cancelUrl, CancellationToken ct);

    // Post-payment recovery. The success redirect hands the browser the provider's own
    // checkout-session id; this resolves that id to the transaction id recorded on the
    // Order, so the success page can show the buyer their download immediately instead of
    // depending on a fulfilment email arriving. Returns null when the session is unknown,
    // not yet paid, or the provider cannot resolve one — the caller then falls back to
    // telling the buyer to check their email.
    //
    // Default implementation returns null so providers that have no session concept (Paddle,
    // whose checkout is a frontend overlay) need no change.
    Task<string?> ResolvePaidTransactionIdAsync(string sessionId, CancellationToken ct)
        => Task.FromResult<string?>(null);
}
