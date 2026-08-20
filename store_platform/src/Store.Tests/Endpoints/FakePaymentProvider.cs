using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Store.Api.Payments;
using Store.Api.Services;

namespace Store.Tests.Endpoints;

/// <summary>A payment rail whose billability answer is set by the test.</summary>
/// <remarks>
/// Everything except <see cref="CanBillPriceAsync"/> throws: a test that reaches real
/// provisioning or checkout through this fake has strayed from what it claims to cover, and
/// should fail loudly rather than quietly exercise a stub.
/// </remarks>
public sealed class FakePaymentProvider : IPaymentProvider
{
    public bool CanBill { get; set; } = true;

    /// <summary>Price ids the endpoint actually asked about — proves the question was put at all.</summary>
    public IList<string> Asked { get; } = [];

    /// <summary>
    /// What <see cref="CreateCheckoutAsync"/> returns. Null keeps the throw-loudly default, so a
    /// test that reaches checkout without opting in still fails rather than exercising a stub.
    /// </summary>
    public CheckoutHandle? HostedHandle { get; set; }

    /// <summary>
    /// What <see cref="CreateEmbeddedCheckoutAsync"/> returns. Null models a provider with no
    /// embedded surface — the case the hosted fallback exists for — and is what the interface's
    /// default implementation returns, so leaving it unset is realistic rather than a stub.
    /// </summary>
    public CheckoutHandle? EmbeddedHandle { get; set; }

    /// <summary>How many times the embedded surface was asked for. Pins that a request the
    /// storefront did NOT make is not made on its behalf.</summary>
    public int EmbeddedCalls { get; private set; }

    /// <summary>Return urls the embedded path was given, to prove the session-id template survives.</summary>
    public IList<string> EmbeddedReturnUrls { get; } = [];

    /// <summary>
    /// Checkout-session id → the paid transaction id the rail reports for it. A session that is
    /// absent resolves to null, which is the real provider's answer for "unknown, or not paid
    /// yet" — so the not-yet-paid case needs no opt-in and is the default.
    /// </summary>
    public IDictionary<string, string> PaidTransactions { get; } = new Dictionary<string, string>(StringComparer.Ordinal);

    public string Name => "stripe";

    public Task<string?> ResolvePaidTransactionIdAsync(string sessionId, CancellationToken ct) =>
        Task.FromResult(PaidTransactions.TryGetValue(sessionId, out var txn) ? txn : null);

    public Task<bool> CanBillPriceAsync(string providerPriceId, CancellationToken ct)
    {
        Asked.Add(providerPriceId);
        return Task.FromResult(CanBill);
    }

    public Task<WebhookVerifyResult> VerifyAndParseAsync(
        HttpRequest request, string rawBody, IConfiguration config, ILogger logger) =>
        throw new NotSupportedException();

    public Task<ProviderProduct> CreateProductAsync(
        string title, long pricePence, string currency, IDictionary<string, string> metadata, CancellationToken ct) =>
        throw new NotSupportedException();

    /// <summary>
    /// Every correlation id handed to this provider, hosted and embedded alike, in call order.
    /// </summary>
    /// <remarks>
    /// Recorded rather than asserted here so a test can prove the endpoint actually passed the
    /// buyer's id down. Without this the whole chain could be wired and pass its unit tests
    /// while the endpoint quietly sent null.
    /// </remarks>
    public IList<string?> CorrelationIds { get; } = [];

    public Task<CheckoutHandle> CreateCheckoutAsync(
        IReadOnlyList<CheckoutLine> lines, string? buyerEmail, string successUrl, string cancelUrl,
        string? correlationId, CancellationToken ct)
    {
        CorrelationIds.Add(correlationId);
        return HostedHandle is null
            ? throw new NotSupportedException()
            : Task.FromResult(HostedHandle);
    }

    public Task<CheckoutHandle?> CreateEmbeddedCheckoutAsync(
        IReadOnlyList<CheckoutLine> lines, string? buyerEmail, string returnUrl, string? correlationId,
        CancellationToken ct)
    {
        EmbeddedCalls++;
        EmbeddedReturnUrls.Add(returnUrl);
        CorrelationIds.Add(correlationId);
        return Task.FromResult(EmbeddedHandle);
    }
}
