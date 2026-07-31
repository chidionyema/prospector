using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Store.Api.Payments;

namespace Store.Tests.Endpoints;

/// <summary>
/// A hidden pack is off the shelf but still a real, honestly-priced sale.
/// </summary>
/// <remarks>
/// Exists so fulfilment can be proved end to end, repeatably, for the price of one cheap pack.
/// The 50p smoke price cannot do that: the underpayment fence (FulfilmentService.cs:88) refuses
/// to grant an entitlement below list price, which is exactly what stops a repriced session
/// minting free packs. Paying a £1 pack's full £1 clears that fence honestly.
/// <para>
/// The danger in this feature is that it looks like a sellability switch. It is not, and the
/// last two tests here are the ones that matter: an unlisted pack must still be unbuyable, or
/// withdrawing a pack from sale has stopped meaning anything.
/// </para>
/// </remarks>
public sealed class HiddenFromCatalogueTests : IClassFixture<StoreApiFactory>
{
    private readonly StoreApiFactory _factory;

    public HiddenFromCatalogueTests(StoreApiFactory factory) => _factory = factory;

    private HttpClient Client()
    {
        var client = _factory.CreateClient();
        client.DefaultRequestHeaders.Add("X-Internal-Key", StoreApiFactory.InternalKey);
        return client;
    }

    private async Task<string> PublishAsync(string id, bool isListed, bool hidden)
    {
        _factory.Payments.CanBill = true;
        var response = await Client().PostAsJsonAsync("/internal/catalog", new
        {
            id,
            title = $"Pack {id}",
            oneLine = "One line.",
            dossierRef = $"dossier:{id}",
            paymentProvider = "stripe",
            providerProductId = "prod_1",
            providerPriceId = "price_real",
            isListed,
            pricePence = 100,
            contentKey = $"packs/{id}/abc.zip",
            contentHash = "abc",
            hiddenFromCatalogue = hidden,
        });
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        return id;
    }

    private async Task<List<string>> CatalogueIdsAsync()
    {
        var response = await _factory.CreateClient().GetAsync("/catalog");
        response.EnsureSuccessStatusCode();
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return doc.RootElement.EnumerateArray()
            .Select(p => p.GetProperty("id").GetString()!)
            .ToList();
    }

    [Fact]
    public async Task A_hidden_pack_is_absent_from_the_browse_catalogue()
    {
        await PublishAsync("hidden-1", isListed: true, hidden: true);
        await PublishAsync("shelf-1", isListed: true, hidden: false);

        var ids = await CatalogueIdsAsync();

        Assert.Contains("shelf-1", ids, StringComparer.Ordinal);
        Assert.DoesNotContain("hidden-1", ids, StringComparer.Ordinal);
    }

    [Fact]
    public async Task A_hidden_pack_still_has_a_pack_page()
    {
        // Without this it could not be bought at all: /catalog/{id} is the sole source for the
        // page the buy button lives on.
        await PublishAsync("hidden-2", isListed: true, hidden: true);

        var response = await _factory.CreateClient().GetAsync("/catalog/hidden-2");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [Fact]
    public async Task A_hidden_pack_is_still_buyable()
    {
        // The whole point: a real sale at its real price, so fulfilment runs for real.
        await PublishAsync("hidden-3", isListed: true, hidden: true);
        _factory.Payments.HostedHandle = new CheckoutHandle("https://pay.example/session", string.Empty);

        var response = await Client().PostAsJsonAsync("/packs/hidden-3/checkout", new { });

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [Fact]
    public async Task Hidden_packs_do_not_inflate_the_public_catalogue_stats()
    {
        // These counts are shown to buyers as survivorship proof. An internal probe pack
        // cleared no gates and is not on offer, so it belongs in neither number.
        await PublishAsync("hidden-4", isListed: true, hidden: true);
        await PublishAsync("shelf-4", isListed: true, hidden: false);

        var response = await _factory.CreateClient().GetAsync("/catalog/stats");
        response.EnsureSuccessStatusCode();
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());

        var listed = doc.RootElement.GetProperty("listed").GetInt32();
        var registered = doc.RootElement.GetProperty("registered").GetInt32();
        var ids = await CatalogueIdsAsync();

        Assert.Equal(ids.Count, listed);
        Assert.DoesNotContain("hidden-4", ids, StringComparer.Ordinal);
        // Registered counts more than listed in general, but never a hidden pack.
        Assert.True(registered >= listed);
        Assert.DoesNotContain("hidden-4", await CatalogueIdsAsync(), StringComparer.Ordinal);
    }

    [Fact]
    public async Task An_unlisted_pack_is_still_unbuyable_hidden_or_not()
    {
        // THE regression guard. IsListed is what makes withdrawing a pack stop the sale
        // (Program.cs:206, CheckoutEndpoints.cs:271). HiddenFromCatalogue must not have
        // become a second door into that fence.
        await PublishAsync("quarantined", isListed: false, hidden: false);
        _factory.Payments.HostedHandle = new CheckoutHandle("https://pay.example/session", string.Empty);

        var response = await Client().PostAsJsonAsync("/packs/quarantined/checkout", new { });

        Assert.NotEqual(HttpStatusCode.OK, response.StatusCode);
    }

    [Fact]
    public async Task An_unlisted_pack_has_no_pack_page_even_when_not_hidden()
    {
        await PublishAsync("quarantined-2", isListed: false, hidden: false);

        var response = await _factory.CreateClient().GetAsync("/catalog/quarantined-2");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }
}
