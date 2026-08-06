using System.Globalization;
using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.Extensions.DependencyInjection;
using Store.Catalog.Persistence;

namespace Store.Tests.Endpoints;

/// <summary>
/// GET /internal/catalog/{id}/price-history (Program.cs GetPackPriceHistory) — the only reader of
/// PackPriceHistory.
/// </summary>
/// <remarks>
/// The table was written from the day the re-price endpoint shipped and read by nothing: a grep
/// for PackPriceHistory across src/ returned four hits — the class, the DbSet, the EF config, and
/// one `.Add(`. Zero queries, zero endpoints, zero tests. A price move was therefore recorded and
/// unretrievable at the same time, which is the same practical state as not recording it: the
/// entity's stated purpose is that "a conversion tells you nothing unless you can say what the
/// buyer was shown", and nothing could say.
///
/// These tests cover the part that is easy to get wrong once and then wrong everywhere, because
/// the answer is NOT the rows. Publish assigns PricePence on INSERT and writes no history row, so
/// the first price exists only as the first row's FromPence, and a never-re-priced pack has an
/// empty history and a real price. Any caller doing its own point-in-time lookup over the raw
/// rows has to rediscover that, and the failure is silent: it reports "no price" for the entire
/// era before the first change, which is exactly the era most sales are in.
/// </remarks>
public sealed class PriceHistoryTests : IClassFixture<StoreApiFactory>
{
    private readonly StoreApiFactory _factory;

    public PriceHistoryTests(StoreApiFactory factory) => _factory = factory;

    private HttpClient Client(bool withKey = true)
    {
        var client = _factory.CreateClient();
        if (withKey) client.DefaultRequestHeaders.Add("X-Internal-Key", StoreApiFactory.InternalKey);
        return client;
    }

    private async Task PublishAsync(string id, long pricePence = 4900)
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
            ["pricePence"] = pricePence,
            ["isListed"] = true,
            ["contentKey"] = $"packs/{id}/hash.zip",
            ["contentHash"] = "hash",
        };
        var response = await Client().PostAsJsonAsync("/internal/catalog", body);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    private async Task PatchAsync(string id, long pricePence, string reason = "L1 ladder v1", string actor = "price-engine")
    {
        var body = new
        {
            pricePence,
            providerPriceId = $"price_{pricePence}",
            reason,
            actor,
            rationaleRef = $"store/pricing/rationale/{id}.json",
        };
        var response = await Client().PatchAsJsonAsync($"/internal/catalog/{id}/price", body);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    private async Task<JsonElement> HistoryAsync(string id, string query = "")
    {
        var response = await Client().GetAsync($"/internal/catalog/{id}/price-history{query}");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return doc.RootElement.Clone();
    }

    private static string AsOf(DateTime when) =>
        "?asOf=" + Uri.EscapeDataString(when.ToString("O", CultureInfo.InvariantCulture));

    // --- the record itself ---

    [Fact]
    public async Task Returns_the_derivation_the_patch_response_never_shows()
    {
        await PublishAsync("ph-basic");
        await PatchAsync("ph-basic", 7900, reason: "comparables moved the rung", actor: "price-engine");

        var history = await HistoryAsync("ph-basic");

        Assert.Equal(1, history.GetProperty("changeCount").GetInt32());
        var row = history.GetProperty("history").EnumerateArray().Single();
        Assert.Equal(4900, row.GetProperty("fromPence").GetInt64());
        Assert.Equal(7900, row.GetProperty("toPence").GetInt64());

        // Reason, actor and the rationale pointer are the whole point: the price is the claim,
        // that file is the receipt. A history that returned only the numbers would answer "what"
        // and leave "why" exactly as unretrievable as before.
        Assert.Equal("comparables moved the rung", row.GetProperty("reason").GetString());
        Assert.Equal("price-engine", row.GetProperty("actor").GetString());
        Assert.Equal("store/pricing/rationale/ph-basic.json", row.GetProperty("rationaleRef").GetString());

        // The floor as it stood at the change, not as it stands now — reading a past sale's
        // legitimacy back needs the floor of that era.
        Assert.Equal(4900, row.GetProperty("minBillablePence").GetInt64());
    }

    [Fact]
    public async Task A_pack_never_repriced_reports_its_price_not_an_empty_record()
    {
        await PublishAsync("ph-virgin", 2900);

        var history = await HistoryAsync("ph-virgin");

        // The failure this exists to prevent: publish writes no history row, so the rows alone
        // say nothing at all about a pack that has sold at one price since launch.
        Assert.Equal(0, history.GetProperty("changeCount").GetInt32());
        Assert.Equal(2900, history.GetProperty("originPricePence").GetInt64());
        Assert.Equal(2900, history.GetProperty("currentPricePence").GetInt64());
        Assert.True(history.GetProperty("continuous").GetBoolean());
    }

    // --- point in time: the question the table was built to answer ---

    [Fact]
    public async Task Reconstructs_the_price_a_buyer_was_shown_before_the_first_change()
    {
        await PublishAsync("ph-origin", 4900);
        await PatchAsync("ph-origin", 9900);

        var history = await HistoryAsync("ph-origin");
        var changedAt = history.GetProperty("history").EnumerateArray().Single()
            .GetProperty("createdAt").GetDateTime();

        var before = await HistoryAsync("ph-origin", AsOf(changedAt.AddMilliseconds(-1)));
        var at = before.GetProperty("asOf");

        // A sale one tick before the re-price was billed £49, and the only record of £49 anywhere
        // is FromPence on the row that replaced it.
        Assert.Equal("origin", at.GetProperty("source").GetString());
        Assert.Equal(4900, at.GetProperty("pricePence").GetInt64());

        // The floor and provider price of that era were never recorded. Null says so; echoing
        // today's values would lend the answer a precision it does not have.
        Assert.Equal(JsonValueKind.Null, at.GetProperty("minBillablePence").ValueKind);
        Assert.Equal(JsonValueKind.Null, at.GetProperty("providerPriceId").ValueKind);
    }

    [Fact]
    public async Task A_sale_stamped_at_the_change_instant_paid_the_new_price()
    {
        await PublishAsync("ph-boundary", 4900);
        await PatchAsync("ph-boundary", 7900);

        var history = await HistoryAsync("ph-boundary");
        var row = history.GetProperty("history").EnumerateArray().Single();
        var changedAt = row.GetProperty("createdAt").GetDateTime();

        var at = (await HistoryAsync("ph-boundary", AsOf(changedAt))).GetProperty("asOf");

        // The change is live from its own CreatedAt. An exclusive boundary would attribute a sale
        // made in the same instant to the old price and under-report the take by £30.
        Assert.Equal("history", at.GetProperty("source").GetString());
        Assert.Equal(7900, at.GetProperty("pricePence").GetInt64());
        Assert.Equal(row.GetProperty("id").GetInt64(), at.GetProperty("changeId").GetInt64());
    }

    [Fact]
    public async Task Walks_back_through_several_changes_to_the_right_window()
    {
        await PublishAsync("ph-walk", 1900);
        await PatchAsync("ph-walk", 4900);
        await PatchAsync("ph-walk", 7900);
        await PatchAsync("ph-walk", 2900);

        var history = await HistoryAsync("ph-walk");
        // Newest first on the way out, so the middle change is index 1.
        var rows = history.GetProperty("history").EnumerateArray().ToList();
        Assert.Equal(2900, rows[0].GetProperty("toPence").GetInt64());
        Assert.Equal(7900, rows[1].GetProperty("toPence").GetInt64());
        Assert.Equal(4900, rows[2].GetProperty("toPence").GetInt64());

        var middle = rows[1].GetProperty("createdAt").GetDateTime();
        var at = (await HistoryAsync("ph-walk", AsOf(middle))).GetProperty("asOf");

        // Not the newest change, and not the oldest: the one actually live at that moment.
        Assert.Equal(7900, at.GetProperty("pricePence").GetInt64());
    }

    [Fact]
    public async Task A_timestamp_before_the_pack_existed_is_not_a_price()
    {
        await PublishAsync("ph-early", 4900);
        await PatchAsync("ph-early", 7900);

        var history = await HistoryAsync("ph-early");
        var publishedAt = history.GetProperty("publishedAt").GetDateTime();

        var at = (await HistoryAsync("ph-early", AsOf(publishedAt.AddMinutes(-5)))).GetProperty("asOf");

        // Distinct from "origin". Reporting £49 here would invent a listing that was never on
        // sale, and any funnel analysis reading it would attribute traffic to a pack that did
        // not exist.
        Assert.Equal("before-publish", at.GetProperty("source").GetString());
        Assert.Equal(JsonValueKind.Null, at.GetProperty("pricePence").ValueKind);
    }

    // --- is the record trustworthy? ---

    [Fact]
    public async Task Reports_a_broken_chain_rather_than_a_plausible_one()
    {
        await PublishAsync("ph-gap", 4900);
        await PatchAsync("ph-gap", 7900);

        Assert.True((await HistoryAsync("ph-gap")).GetProperty("continuous").GetBoolean());

        // Simulate the thing that makes this record worthless: a price written without a history
        // row. PricePence has exactly two assignment sites today and both are covered, so this
        // cannot currently happen through the API — which is the point. `continuous` is what
        // still holds when a third writer is added later, and it is the difference between a
        // history that is wrong and a history that says it is wrong.
        using (var scope = _factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<StoreDbContext>();
            var pack = await db.Packs.FindAsync("ph-gap");
            pack!.PricePence = 12900;
            await db.SaveChangesAsync();
        }

        var history = await HistoryAsync("ph-gap");
        Assert.False(
            history.GetProperty("continuous").GetBoolean(),
            "a price moved with no history row and the record still claimed to be complete");
        Assert.Equal(12900, history.GetProperty("currentPricePence").GetInt64());
    }

    [Fact]
    public async Task The_limit_bounds_the_response_not_the_analysis()
    {
        await PublishAsync("ph-limit", 1900);
        await PatchAsync("ph-limit", 2900);
        await PatchAsync("ph-limit", 4900);
        await PatchAsync("ph-limit", 7900);

        var history = await HistoryAsync("ph-limit", "?limit=1");

        Assert.Single(history.GetProperty("history").EnumerateArray());
        Assert.True(history.GetProperty("truncated").GetBoolean());

        // Computed over the whole chain, not the page. Truncating first would make a complete
        // history read as a broken one and raise exactly the alarm the flag exists to raise
        // honestly: originPricePence would become 4900 and continuous would go false.
        Assert.Equal(3, history.GetProperty("changeCount").GetInt32());
        Assert.Equal(1900, history.GetProperty("originPricePence").GetInt64());
        Assert.True(history.GetProperty("continuous").GetBoolean());
    }

    // --- the guards ---

    [Fact]
    public async Task Refuses_without_the_internal_key()
    {
        await PublishAsync("ph-auth");

        // reason/actor lines are operational notes, and a public price-change log hands a
        // competitor every pricing experiment we have run, including the abandoned ones.
        var response = await Client(withKey: false).GetAsync("/internal/catalog/ph-auth/price-history");
        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Unknown_pack_is_404_not_an_empty_history()
    {
        // An empty 200 would read as "this pack has never been re-priced", which is a different
        // and reassuring fact.
        var response = await Client().GetAsync("/internal/catalog/ph-nope/price-history");
        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }
}
