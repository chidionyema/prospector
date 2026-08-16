using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging.Abstractions;
using Store.Api.Payments;

namespace Store.Tests.Payments;

/// <summary>
/// A price id proves nothing by itself. It has the same shape whichever Stripe account minted
/// it, so a publisher holding the wrong key produces ids that look perfect and cannot be
/// charged — which is exactly what put 10 unbuyable packs on sale on 2026-07-31, each rendering
/// a buy button that returned HTTP 500.
/// </summary>
/// <remarks>
/// These cover the answers reachable without a network. The account-mismatch case — the one
/// that actually bit — is only answerable by asking Stripe with our own key, which is the
/// reason the check lives on the provider rather than in string validation.
/// </remarks>
public sealed class BillablePriceGateTests
{
    private static StripeProvider Provider() =>
        new(new ConfigurationBuilder()
                .AddInMemoryCollection(new Dictionary<string, string?>(StringComparer.Ordinal)
                {
                    ["Stripe:ApiKey"] = "sk_test_123",
                })
                .Build(),
            NullLogger<StripeProvider>.Instance);

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    public async Task A_missing_price_is_not_billable(string priceId)
    {
        Assert.False(await Provider().CanBillPriceAsync(priceId, CancellationToken.None));
    }

    [Fact]
    public async Task A_stub_price_is_not_billable()
    {
        // bridge.py assigns `price_stub_{id}` as a pre-provisioning fallback. Refused here
        // without a network call so the answer holds even when Stripe is unreachable.
        Assert.False(await Provider().CanBillPriceAsync("price_stub_abc123", CancellationToken.None));
    }
}
