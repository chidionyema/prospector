using System.Net;
using System.Net.Http.Json;
using System.Text.Json;

namespace Store.Tests.Endpoints;

/// <summary>
/// PATCH /internal/catalog/{id}/facets, market field — the narrow door for correcting a pack's
/// jurisdiction tag.
/// </summary>
/// <remarks>
/// The failure this exists for, measured on the live catalogue 2026-08-14: three of fifty-nine
/// listed packs carried a null Market while their own dossiers recorded "uk". Both readers of
/// the field treat null as "uk" by default (the /catalog `?market=` filter and the storefront's
/// groupByMarket), so those packs were printed under "Built for UK rules" on the strength of a
/// default rather than a fact — and the only write path that could set Market was the
/// /internal/catalog upsert, which assigns provider ids unconditionally. Correcting a browse
/// tag must never require holding the money rail.
/// </remarks>
public sealed class FacetPatchMarketTests : IClassFixture<StoreApiFactory>
{
    private readonly StoreApiFactory _factory;

    public FacetPatchMarketTests(StoreApiFactory factory) => _factory = factory;

    private HttpClient Client()
    {
        var client = _factory.CreateClient();
        client.DefaultRequestHeaders.Add("X-Internal-Key", StoreApiFactory.InternalKey);
        return client;
    }

    private async Task PublishAsync(string id, string? market = null)
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
            ["contentKey"] = $"packs/{id}/hash.zip",
            ["contentHash"] = "hash",
        };
        if (market is not null) body["market"] = market;

        var response = await Client().PostAsJsonAsync("/internal/catalog", body);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    private static async Task<JsonElement> BodyOf(HttpResponseMessage response)
    {
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return doc.RootElement.Clone();
    }

    [Fact]
    public async Task Sets_the_market_on_a_pack_that_was_published_without_one()
    {
        await PublishAsync("fm-null");

        var response = await Client().PatchAsJsonAsync(
            "/internal/catalog/fm-null/facets", new { market = "uk" });

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("uk", (await BodyOf(response)).GetProperty("market").GetString());
    }

    [Fact]
    public async Task Omitting_market_leaves_an_existing_one_alone()
    {
        // The null rule, on the field most likely to be collateral damage: a facet backfill
        // sends sector and nothing else, and must not blank the jurisdiction on its way past.
        await PublishAsync("fm-keep", market: "us");

        var response = await Client().PatchAsJsonAsync(
            "/internal/catalog/fm-keep/facets", new { sector = "pets_animals" });

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("us", (await BodyOf(response)).GetProperty("market").GetString());
    }

    [Fact]
    public async Task An_empty_string_withdraws_a_wrong_market()
    {
        // Untagging has to be reachable or the null-means-no-change rule is a one-way door:
        // a pack wrongly tagged "us" could never be returned to "we did not determine this".
        await PublishAsync("fm-clear", market: "us");

        var response = await Client().PatchAsJsonAsync(
            "/internal/catalog/fm-clear/facets", new { market = "" });

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal(JsonValueKind.Null, (await BodyOf(response)).GetProperty("market").ValueKind);
    }

    [Theory]
    [InlineData("us-tx")]
    [InlineData("ca-on")]
    public async Task Accepts_the_hierarchical_codes_the_domain_declares(string code)
    {
        await PublishAsync($"fm-{code}");

        var response = await Client().PatchAsJsonAsync(
            $"/internal/catalog/fm-{code}/facets", new { market = code });

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal(code, (await BodyOf(response)).GetProperty("market").GetString());
    }

    [Theory]
    [InlineData("UK")]          // uppercase would form a second shelf beside "uk", not join it
    [InlineData("united-kingdom")]
    [InlineData("uk\r\nSet-Cookie: x=1")]
    public async Task Rejects_anything_that_is_not_a_market_code_and_writes_nothing(string bad)
    {
        await PublishAsync("fm-bad", market: "uk");

        var response = await Client().PatchAsJsonAsync(
            "/internal/catalog/fm-bad/facets", new { market = bad, sector = "pets_animals" });

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);

        // The rejection has to be total: the sector rode along in the same payload, and a
        // half-applied write is how a filter starts making a claim the engine never made.
        var after = await Client().GetAsync("/catalog/fm-bad");
        Assert.Equal(HttpStatusCode.OK, after.StatusCode);
        var body = await BodyOf(after);
        Assert.Equal("uk", body.GetProperty("market").GetString());
        Assert.Equal(JsonValueKind.Null, body.GetProperty("sector").ValueKind);
    }
}
