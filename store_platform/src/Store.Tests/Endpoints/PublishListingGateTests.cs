using System.Net;
using System.Net.Http.Json;
using System.Text.Json;

namespace Store.Tests.Endpoints;

/// <summary>
/// The publish endpoint decides whether a pack goes on sale. These prove the decision is wired,
/// not merely implemented.
/// </summary>
/// <remarks>
/// The failure being fenced: on 2026-07-31 a publisher holding a sandbox Stripe key listed 10
/// packs whose price ids were perfectly well-formed and chargeable by no account this Store can
/// reach. Every buy button returned HTTP 500 until someone tested checkout by hand. Shape checks
/// cannot see it — only asking our own money rail can.
/// </remarks>
public sealed class PublishListingGateTests : IClassFixture<StoreApiFactory>
{
    private readonly StoreApiFactory _factory;

    public PublishListingGateTests(StoreApiFactory factory) => _factory = factory;

    private HttpClient Client()
    {
        var client = _factory.CreateClient();
        client.DefaultRequestHeaders.Add("X-Internal-Key", StoreApiFactory.InternalKey);
        return client;
    }

    private static object Publish(string id, string priceId) => new
    {
        id,
        title = "A Pack",
        oneLine = "One line.",
        dossierRef = $"dossier:{id}",
        paymentProvider = "stripe",
        providerProductId = "prod_1",
        providerPriceId = priceId,
        isListed = true,
        contentKey = $"packs/{id}/abc.zip",
        contentHash = "abc",
    };

    private static async Task<bool> IsListedAsync(HttpResponseMessage response)
    {
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return doc.RootElement.GetProperty("isListed").GetBoolean();
    }

    [Fact]
    public async Task A_billable_pack_lists()
    {
        _factory.Payments.CanBill = true;
        var id = "pack-billable";

        var response = await Client().PostAsJsonAsync("/internal/catalog", Publish(id, "price_real"));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.True(await IsListedAsync(response));
    }

    [Fact]
    public async Task An_unbillable_pack_is_stored_but_never_listed()
    {
        // The whole point. The publish still succeeds — the pack is recorded so a later run can
        // list it once its price is real — but it must not go on sale meanwhile. Unlisted is
        // recoverable; a buy button that 500s spends the buyer's trust before we learn of it.
        _factory.Payments.CanBill = false;
        var id = "pack-unbillable";

        var response = await Client().PostAsJsonAsync("/internal/catalog", Publish(id, "price_from_wrong_account"));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.False(await IsListedAsync(response));
    }

    [Fact]
    public async Task The_endpoint_actually_asks_the_money_rail()
    {
        // Pins the wiring itself: without this, deleting the guard from Program.cs leaves the
        // billability tests passing and the fence gone.
        _factory.Payments.Asked.Clear();
        _factory.Payments.CanBill = true;

        await Client().PostAsJsonAsync("/internal/catalog", Publish("pack-asks", "price_asked_about"));

        Assert.Contains("price_asked_about", _factory.Payments.Asked, StringComparer.Ordinal);
    }

    [Fact]
    public async Task Billability_is_not_consulted_when_the_pack_is_not_going_live()
    {
        // An unlisted publish is a registration, not a sale, so it must not cost a Stripe call.
        // The engine registers packs unlisted routinely (incomplete bundle, upload failed).
        _factory.Payments.Asked.Clear();
        var body = new
        {
            id = "pack-unlisted",
            title = "A Pack",
            oneLine = "One line.",
            dossierRef = "dossier:pack-unlisted",
            paymentProvider = "stripe",
            providerPriceId = "price_whatever",
            isListed = false,
            contentKey = "packs/pack-unlisted/abc.zip",
        };

        var response = await Client().PostAsJsonAsync("/internal/catalog", body);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.False(await IsListedAsync(response));
        Assert.Empty(_factory.Payments.Asked);
    }

    [Fact]
    public async Task An_unauthenticated_publish_is_refused()
    {
        // Included because the auth check is wiring too, and nothing exercised it before.
        var response = await _factory.CreateClient()
            .PostAsJsonAsync("/internal/catalog", Publish("pack-noauth", "price_real"));

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }
}
