using System.Net;
using System.Net.Http.Json;
using System.Text.Json;

namespace Store.Tests.Endpoints;

/// <summary>
/// `?market=` on GET /catalog is a boost-don't-block filter for the storefront's geo-aware
/// shelf (Program.cs GetCatalog), not a second sellability fence like <see cref="HiddenFromCatalogueTests"/>.
/// </summary>
/// <remarks>
/// The rule that matters most here is the null-is-uk one: most live packs predate the engine
/// tracking markets at all, so an untagged pack must still surface under `?market=uk` — the
/// storefront makes the same assumption when it groups the catalogue by market, and the two
/// sides would silently disagree the day this drifted.
/// </remarks>
public sealed class CatalogMarketFilterTests : IClassFixture<StoreApiFactory>
{
    private readonly StoreApiFactory _factory;

    public CatalogMarketFilterTests(StoreApiFactory factory) => _factory = factory;

    private HttpClient Client()
    {
        var client = _factory.CreateClient();
        client.DefaultRequestHeaders.Add("X-Internal-Key", StoreApiFactory.InternalKey);
        return client;
    }

    private async Task PublishAsync(string id, string? market)
    {
        _factory.Payments.CanBill = true;
        var body = new Dictionary<string, object?>(StringComparer.Ordinal)
        {
            ["id"] = id,
            ["title"] = $"Pack {id}",
            ["oneLine"] = "One line.",
            ["dossierRef"] = $"dossier:{id}",
            ["paymentProvider"] = "stripe",
            ["providerProductId"] = "prod_1",
            ["providerPriceId"] = "price_real",
            ["isListed"] = true,
            ["contentKey"] = $"packs/{id}/abc.zip",
            ["contentHash"] = "abc",
        };
        if (market is not null) body["market"] = market;

        var response = await Client().PostAsJsonAsync("/internal/catalog", body);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    private async Task<List<string>> CatalogueIdsAsync(string? market = null)
    {
        var url = market is null ? "/catalog" : $"/catalog?market={Uri.EscapeDataString(market)}";
        var response = await _factory.CreateClient().GetAsync(url);
        response.EnsureSuccessStatusCode();
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return doc.RootElement.EnumerateArray()
            .Select(p => p.GetProperty("id").GetString()!)
            .ToList();
    }

    [Fact]
    public async Task No_param_returns_every_listed_pack_regardless_of_market()
    {
        await PublishAsync("market-none-uk", "uk");
        await PublishAsync("market-none-us", "us");
        await PublishAsync("market-none-null", null);

        var ids = await CatalogueIdsAsync();

        Assert.Contains("market-none-uk", ids, StringComparer.Ordinal);
        Assert.Contains("market-none-us", ids, StringComparer.Ordinal);
        Assert.Contains("market-none-null", ids, StringComparer.Ordinal);
    }

    [Fact]
    public async Task Market_us_returns_only_us_packs()
    {
        await PublishAsync("market-us-a", "us");
        await PublishAsync("market-us-b", "uk");
        await PublishAsync("market-us-c", null);

        var ids = await CatalogueIdsAsync("us");

        Assert.Contains("market-us-a", ids, StringComparer.Ordinal);
        Assert.DoesNotContain("market-us-b", ids, StringComparer.Ordinal);
        Assert.DoesNotContain("market-us-c", ids, StringComparer.Ordinal);
    }

    [Fact]
    public async Task Market_uk_includes_packs_with_no_market_recorded()
    {
        // The regression this guards: a pack published before the engine tracked markets must
        // not vanish from `?market=uk` the day this filter shipped — it is a UK pack by every
        // fact the storefront has, it just never got tagged.
        await PublishAsync("market-uk-tagged", "uk");
        await PublishAsync("market-uk-untagged", null);
        await PublishAsync("market-uk-us", "us");

        var ids = await CatalogueIdsAsync("uk");

        Assert.Contains("market-uk-tagged", ids, StringComparer.Ordinal);
        Assert.Contains("market-uk-untagged", ids, StringComparer.Ordinal);
        Assert.DoesNotContain("market-uk-us", ids, StringComparer.Ordinal);
    }
}
