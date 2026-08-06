using System.Net;
using System.Net.Http.Json;
using System.Text.Json;

namespace Store.Tests.Endpoints;

/// <summary>
/// The audience persona the engine generated a pack for has to survive the publish boundary
/// and be served on both read endpoints, or nothing downstream can ask which persona sells.
/// </summary>
/// <remarks>
/// The dossiers carried this value on 1419 of 1625 indexed rows and the publish boundary threw
/// it away, so the catalogue could say what a pack was but never who it was aimed at. Modelled
/// on <see cref="CardLineTests"/> for the same reason it exists: the publish POST returns 200
/// with an unmodelled field silently ignored, so a green publish is not evidence that a field
/// landed — only a read-back is.
/// </remarks>
public sealed class PackAudienceTests : IClassFixture<StoreApiFactory>
{
    private readonly StoreApiFactory _factory;

    public PackAudienceTests(StoreApiFactory factory) => _factory = factory;

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
            ["title"] = "Deposit Dispute Kit",
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

    private static string? ReadAudience(JsonElement element)
    {
        var value = element.GetProperty("audience");
        return value.ValueKind == JsonValueKind.Null ? null : value.GetString();
    }

    private async Task<string?> DetailAudienceAsync(string id)
    {
        var response = await Client().GetAsync($"/catalog/{id}");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return ReadAudience(doc.RootElement);
    }

    private async Task<string?> ListAudienceAsync(string id)
    {
        var response = await Client().GetAsync("/catalog");
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var row = doc.RootElement.EnumerateArray()
            .Single(p => string.Equals(p.GetProperty("id").GetString(), id, StringComparison.Ordinal));
        return ReadAudience(row);
    }

    [Fact]
    public async Task A_published_audience_is_served_on_both_read_endpoints()
    {
        // Both, not one. The shelf renders from /catalog and the product page from
        // /catalog/{id}; a persona visible on only one of them makes any per-persona
        // measurement depend on which endpoint the caller happened to read.
        const string id = "pack-audience-roundtrip";
        await PublishAsync(id, new { audience = "primary_carer" });

        Assert.Equal("primary_carer", await DetailAudienceAsync(id));
        Assert.Equal("primary_carer", await ListAudienceAsync(id));
    }

    [Fact]
    public async Task A_pack_published_without_one_serves_null_rather_than_a_guess()
    {
        // Every pack published before this field existed is in this state, plus the 26
        // dossiers on disk that generation never stamped. Null means "unknown persona"; a
        // default like "general" would be a claim the engine never made, and it would then
        // be counted as a real cohort by whatever measures conversion per persona.
        const string id = "pack-audience-absent";
        await PublishAsync(id, new { });

        Assert.Null(await DetailAudienceAsync(id));
        Assert.Null(await ListAudienceAsync(id));
    }

    [Fact]
    public async Task A_republish_that_omits_the_audience_leaves_the_stored_one_alone()
    {
        // The engine omits the key entirely rather than sending "" when a candidate carries no
        // persona, so a metadata-light republish of an already-tagged pack must not blank it.
        // Without the `is not null` guard in the apply block this silently untags the pack, and
        // the loss is invisible: the publish still returns 200.
        const string id = "pack-audience-republish";
        await PublishAsync(id, new { audience = "manual_tradesperson" });
        await PublishAsync(id, new { });

        Assert.Equal("manual_tradesperson", await DetailAudienceAsync(id));
    }

    [Fact]
    public async Task An_audience_outside_the_engines_current_list_still_publishes()
    {
        // Deliberately NOT validated against a closed vocabulary, unlike the discovery facets.
        // The persona list lives in the engine's config.yaml (generation.audience_forms) and an
        // operator edits it; a validator here would turn the next addition to that list into a
        // 400 on every publish. Nobody filters the shelf on this field, so an unrecognised
        // value costs a stale label, whereas rejecting it costs the whole publish.
        const string id = "pack-audience-unknown-value";
        await PublishAsync(id, new { audience = "newly_added_persona" });

        Assert.Equal("newly_added_persona", await DetailAudienceAsync(id));
    }
}
