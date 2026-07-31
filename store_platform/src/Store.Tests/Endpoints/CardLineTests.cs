using System.Net;
using System.Net.Http.Json;
using System.Text.Json;

namespace Store.Tests.Endpoints;

/// <summary>
/// The shelf card's heading has to survive the publish boundary and be served on both read
/// endpoints, or the storefront silently falls back to the brand name forever.
/// </summary>
/// <remarks>
/// This is the gap that was open when the column did not exist: the engine sent `cardLine`, the
/// API accepted the POST with a 200, and the value went nowhere. A green publish is not evidence
/// that a field landed — only a read-back is.
/// </remarks>
public sealed class CardLineTests : IClassFixture<StoreApiFactory>
{
    private readonly StoreApiFactory _factory;

    public CardLineTests(StoreApiFactory factory) => _factory = factory;

    private HttpClient Client()
    {
        var client = _factory.CreateClient();
        client.DefaultRequestHeaders.Add("X-Internal-Key", StoreApiFactory.InternalKey);
        return client;
    }

    private async Task PublishAsync(string id, object extra)
    {
        _factory.Payments.CanBill = true;
        var body = new Dictionary<string, object?>(StringComparer.Ordinal)
        {
            ["id"] = id,
            ["title"] = "PitchCall Forensics",
            ["oneLine"] = "One line.",
            ["dossierRef"] = $"dossier:{id}",
            ["paymentProvider"] = "stripe",
            ["providerProductId"] = "prod_1",
            ["providerPriceId"] = "price_real",
            ["isListed"] = true,
            ["contentKey"] = $"packs/{id}/abc.zip",
            ["contentHash"] = "abc",
        };
        foreach (var property in extra.GetType().GetProperties())
        {
            body[property.Name] = property.GetValue(extra);
        }

        var response = await Client().PostAsJsonAsync("/internal/catalog", body);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    private async Task<string?> DetailCardLineAsync(string id)
    {
        var response = await Client().GetAsync($"/catalog/{id}");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var value = doc.RootElement.GetProperty("cardLine");
        return value.ValueKind == JsonValueKind.Null ? null : value.GetString();
    }

    private async Task<string?> ListCardLineAsync(string id)
    {
        var response = await Client().GetAsync("/catalog");
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var row = doc.RootElement.EnumerateArray()
            .Single(p => string.Equals(p.GetProperty("id").GetString(), id, StringComparison.Ordinal));
        var value = row.GetProperty("cardLine");
        return value.ValueKind == JsonValueKind.Null ? null : value.GetString();
    }

    [Fact]
    public async Task A_published_card_line_is_served_on_both_read_endpoints()
    {
        // Both, not one: the shelf renders from /catalog and the product page from /catalog/{id},
        // and a card line present on only one of them is a card that changes when you click it.
        const string id = "pack-cardline-roundtrip";
        await PublishAsync(id, new { cardLine = "Refund insurance excess for under-27 gig drivers" });

        Assert.Equal("Refund insurance excess for under-27 gig drivers", await DetailCardLineAsync(id));
        Assert.Equal("Refund insurance excess for under-27 gig drivers", await ListCardLineAsync(id));
    }

    [Fact]
    public async Task A_pack_published_without_one_serves_null_rather_than_a_guess()
    {
        // Every pack published before this field existed is in this state. Null is the signal the
        // storefront's cardHeading() falls back to the title on; anything invented here would be
        // a claim the engine never made.
        const string id = "pack-cardline-absent";
        await PublishAsync(id, new { });

        Assert.Null(await DetailCardLineAsync(id));
    }

    [Fact]
    public async Task A_republish_that_omits_the_card_line_leaves_the_stored_one_alone()
    {
        // The engine drops an over-length line rather than truncating it, so a later run of the
        // same pack legitimately sends no cardLine at all. If that blanked the column, one
        // unlucky generation would strip the card heading off a pack that already had a good one.
        const string id = "pack-cardline-republish";
        await PublishAsync(id, new { cardLine = "Chase unpaid invoices for two-van trades firms" });
        await PublishAsync(id, new { });

        Assert.Equal("Chase unpaid invoices for two-van trades firms", await DetailCardLineAsync(id));
    }
}
