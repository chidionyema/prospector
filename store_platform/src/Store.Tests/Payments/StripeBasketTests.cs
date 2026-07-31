using System.Security.Cryptography;
using System.Text;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging.Abstractions;
using Store.Api.Payments;

namespace Store.Tests.Payments;

/// <summary>
/// A basket is where the price fence is easiest to lose. FulfilmentService only grants an
/// entitlement when the item's paid amount covers the catalogue price; with one pack per session
/// the session total IS that pack's amount, so the fence held for free. With several packs it
/// does not, and every test here exists to pin the difference.
/// </summary>
public sealed class StripeBasketTests
{
    private const string Secret = "whsec_test";
    private readonly IConfiguration _config;
    private readonly StripeProvider _provider;

    public StripeBasketTests()
    {
        _config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>(StringComparer.Ordinal)
            {
                ["Stripe:WebhookSecret"] = Secret,
                ["Stripe:ApiKey"] = "sk_test_123",
            })
            .Build();
        _provider = new StripeProvider(_config, NullLogger<StripeProvider>.Instance);
    }

    [Fact]
    public void BuildCheckoutMetadata_SinglePack_StillWritesTheSingularKey()
    {
        var metadata = StripeProvider.BuildCheckoutMetadata([new CheckoutLine("pack-1", "price_1")]);

        // Kept because everything outside this codebase that reads a Stripe session — the
        // Dashboard, an export, a support query, and any session still in flight across a
        // deploy — has only ever seen pack_id.
        Assert.Equal("pack-1", metadata["pack_id"]);
        Assert.Equal("pack-1", metadata["pack_ids"]);
        Assert.Equal("price_1", metadata["price_ids"]);
    }

    [Fact]
    public void BuildCheckoutMetadata_Basket_WritesParallelCsvsAndNoSingularKey()
    {
        var metadata = StripeProvider.BuildCheckoutMetadata(
        [
            new CheckoutLine("pack-1", "price_1"),
            new CheckoutLine("pack-2", "price_2"),
            new CheckoutLine("pack-3", "price_3"),
        ]);

        Assert.Equal("pack-1,pack-2,pack-3", metadata["pack_ids"]);
        Assert.Equal("price_1,price_2,price_3", metadata["price_ids"]);
        // A basket has no single pack, and writing one would name an arbitrary member of it.
        Assert.False(metadata.ContainsKey("pack_id"));
    }

    [Fact]
    public void BuildCheckoutMetadata_CsvsStayUnderStripesValueLimit_AtTheLineCap()
    {
        var lines = Enumerable.Range(0, StripeProvider.MaxCheckoutLines)
            .Select(i => new CheckoutLine($"{i:D16}", $"price_1P{i:D24}"))
            .ToArray();

        var metadata = StripeProvider.BuildCheckoutMetadata(lines);

        // Stripe rejects a metadata value over 500 characters. The cap exists to keep both CSVs
        // inside it; if someone raises MaxCheckoutLines without checking, this fails first.
        Assert.All(metadata.Values, value => Assert.True(value.Length <= 500, $"{value.Length} chars"));
    }

    [Fact]
    public void PairBasketItems_GivesEachPackItsOwnPaidAmount()
    {
        var items = StripeProvider.PairBasketItems(
            "cs_1",
            ["pack-1", "pack-2"],
            ["price_1", "price_2"],
            new Dictionary<string, long>(StringComparer.Ordinal) { ["price_1"] = 4900, ["price_2"] = 4900 });

        Assert.Equal(2, items.Count);
        Assert.Equal("pack-1", items[0].ProductId);
        Assert.Equal("pack-2", items[1].ProductId);
        // NOT 9800 each. That is the whole point: the session total is the basket, and handing it
        // to every item would let a £98 payment satisfy a fence asking whether £49 was paid for
        // each of two packs — and would equally clear a fence asking for £200.
        Assert.All(items, item => Assert.Equal(4900, item.AmountPence));
    }

    [Fact]
    public void PairBasketItems_PairsByPriceId_NotByPosition()
    {
        // Stripe does not contractually guarantee the order it returns line items in, so the
        // pairing is by price id. Feed the amounts in reverse and the packs must still get theirs.
        var items = StripeProvider.PairBasketItems(
            "cs_1",
            ["pack-cheap", "pack-dear"],
            ["price_cheap", "price_dear"],
            new Dictionary<string, long>(StringComparer.Ordinal)
            {
                ["price_dear"] = 9900,
                ["price_cheap"] = 4900,
            });

        Assert.Equal(4900, items[0].AmountPence);
        Assert.Equal(9900, items[1].AmountPence);
    }

    [Fact]
    public void PairBasketItems_DiscountedLineKeepsItsDiscountedAmount()
    {
        // A 50%-off coupon lands as a reduced line subtotal. The item must carry the reduced
        // number so FulfilmentService can refuse it, rather than a list price it did not fetch.
        var items = StripeProvider.PairBasketItems(
            "cs_1",
            ["pack-1", "pack-2"],
            ["price_1", "price_2"],
            new Dictionary<string, long>(StringComparer.Ordinal) { ["price_1"] = 2450, ["price_2"] = 4900 });

        Assert.Equal(2450, items[0].AmountPence);
        Assert.Equal(4900, items[1].AmountPence);
    }

    [Fact]
    public void PairBasketItems_MissingLine_RefusesRatherThanGuessing()
    {
        var ex = Assert.Throws<LineItemsUnavailableException>(() => StripeProvider.PairBasketItems(
            "cs_1",
            ["pack-1", "pack-2"],
            ["price_1", "price_2"],
            new Dictionary<string, long>(StringComparer.Ordinal) { ["price_1"] = 4900 }));

        Assert.Contains("price_2", ex.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void PairBasketItems_MismatchedCsvs_RefusesRatherThanGuessing()
    {
        Assert.Throws<LineItemsUnavailableException>(() => StripeProvider.PairBasketItems(
            "cs_1",
            ["pack-1", "pack-2"],
            ["price_1"],
            new Dictionary<string, long>(StringComparer.Ordinal) { ["price_1"] = 4900 }));
    }

    [Fact]
    public async Task VerifyAndParseAsync_SinglePackBasket_ResolvesWithoutCallingStripe()
    {
        // pack_ids with one entry must behave exactly as pack_id always has: the session total is
        // that pack's amount, resolved from the payload alone. The API key here is fake, so if
        // this path ever reached out for line items the call would fail and the test would too.
        var result = await ParseSessionAsync(
            "{\"pack_ids\":\"pack-1\",\"price_ids\":\"price_1\",\"pack_id\":\"pack-1\"}", amountTotal: 5880);

        Assert.True(result.Verified);
        var item = Assert.Single(result.Transaction!.Items);
        Assert.Equal("pack-1", item.ProductId);
        Assert.Equal(5880, item.AmountPence);
    }

    [Fact]
    public async Task VerifyAndParseAsync_LegacySinglePackIdMetadata_StillFulfils()
    {
        // Sessions created before basket checkout shipped may still be in flight.
        var result = await ParseSessionAsync("{\"pack_id\":\"pack-legacy\"}", amountTotal: 4900);

        Assert.True(result.Verified);
        var item = Assert.Single(result.Transaction!.Items);
        Assert.Equal("pack-legacy", item.ProductId);
        Assert.Equal(4900, item.AmountPence);
    }

    [Fact]
    public async Task VerifyAndParseAsync_BasketWithUnpairableMetadata_FailsClosed()
    {
        // Two packs, one price id: unpairable without a guess. The webhook must refuse — never
        // fall back to the session total, which is the failure that would grant both packs on a
        // number that proves nothing about either.
        var result = await ParseSessionAsync(
            "{\"pack_ids\":\"pack-1,pack-2\",\"price_ids\":\"price_1\"}", amountTotal: 9800);

        Assert.False(result.Verified);
        Assert.Equal("line-items-unavailable", result.Reason);
        Assert.Null(result.Transaction);
    }

    /// <summary>Build a signed checkout.session.completed event and run it through the provider.</summary>
    private async Task<WebhookVerifyResult> ParseSessionAsync(string metadataJson, long amountTotal)
    {
        var body =
            "{\"id\":\"evt_1\",\"object\":\"event\",\"type\":\"checkout.session.completed\",\"request\":null," +
            "\"data\":{\"object\":{\"id\":\"cs_1\",\"object\":\"checkout.session\",\"payment_intent\":\"pi_1\"," +
            "\"customer_details\":{\"email\":\"buyer@example.com\",\"address\":{\"country\":\"GB\"}}," +
            $"\"amount_total\":{amountTotal.ToString(System.Globalization.CultureInfo.InvariantCulture)}," +
            $"\"currency\":\"gbp\",\"metadata\":{metadataJson}}}}},\"created\":1718553600}}";

        var timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds()
            .ToString(System.Globalization.CultureInfo.InvariantCulture);
        using var hmac = new HMACSHA256(Encoding.UTF8.GetBytes(Secret));
        var hash = Convert.ToHexStringLower(hmac.ComputeHash(Encoding.UTF8.GetBytes($"{timestamp}.{body}")));

        var request = new DefaultHttpContext().Request;
        request.Headers["Stripe-Signature"] = $"t={timestamp},v1={hash}";

        return await _provider.VerifyAndParseAsync(request, body, _config, NullLogger.Instance);
    }
}
