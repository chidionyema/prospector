using System.Net;
using System.Net.Http.Json;
using System.Text.Json;

namespace Store.Tests.Endpoints;

/// <summary>
/// POST /internal/catalog (Program.cs PublishPack) — a republish may not re-point the money rail
/// of a pack whose price it is not allowed to move.
/// </summary>
/// <remarks>
/// The defect, measured on the live catalogue 2026-08-15. `PricePence` is assigned on INSERT only,
/// deliberately: re-pricing a live pack has to go through PATCH /internal/catalog/{id}/price so the
/// floor drain and the PackPriceHistory row move with it. But `ProviderPriceId` was assigned on
/// every publish that carried one — so a republish moved what the buyer is CHARGED while the shelf
/// number stayed frozen at whatever the pack was first inserted with, and left no trace of it.
///
/// Nine of 59 live packs were in that state. `d6f72b9dc9a45c45` was inserted 2026-08-01 at 4900p and
/// republished on 2026-08-13 when the price-engine decided 9999p: the card read £49.00, Stripe would
/// have charged £99.99, `price-history` showed `changeCount: 0` and an empty history. A second pack
/// sat at £49.00 against £79.99. Two independent records agreed the rail was right and the shelf was
/// stale, which is the only reason the repair was possible at all.
///
/// These tests pin the ASYMMETRY as closed: the pointer now moves only when there is nothing for it
/// to contradict. They are deliberately written against the endpoint rather than against the guard,
/// so they keep holding if the implementation moves.
/// </remarks>
public sealed class PublishPricePointerTests : IClassFixture<StoreApiFactory>
{
    private readonly StoreApiFactory _factory;

    public PublishPricePointerTests(StoreApiFactory factory) => _factory = factory;

    private HttpClient Client()
    {
        var client = _factory.CreateClient();
        client.DefaultRequestHeaders.Add("X-Internal-Key", StoreApiFactory.InternalKey);
        return client;
    }

    /// <summary>One publish body. Everything the endpoint needs, with the two money fields open.</summary>
    private static Dictionary<string, object?> Body(string id, string priceId, long pricePence) =>
        new(StringComparer.Ordinal)
        {
            ["id"] = id,
            ["title"] = $"Pack {id}",
            ["oneLine"] = "One line.",
            ["dossierRef"] = $"dossier:{id}",
            ["paymentProvider"] = "stripe",
            ["providerProductId"] = "prod_real",
            ["providerPriceId"] = priceId,
            ["pricePence"] = pricePence,
            ["isListed"] = true,
            ["contentKey"] = $"packs/{id}/hash.zip",
            ["contentHash"] = "hash",
        };

    private async Task<JsonElement> PublishAsync(string id, string priceId, long pricePence)
    {
        _factory.Payments.CanBill = true;
        var response = await Client().PostAsJsonAsync("/internal/catalog", Body(id, priceId, pricePence));
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        return await response.Content.ReadFromJsonAsync<JsonElement>();
    }

    [Fact]
    public async Task A_republish_carrying_a_different_price_id_does_not_move_the_pointer()
    {
        // Inserted at £49.00 against price_first, exactly as the two damaged packs were.
        var inserted = await PublishAsync("pointer-contested", "price_first", 4900L);
        Assert.Equal("price_first", inserted.GetProperty("providerPriceId").GetString());
        Assert.Equal(4900L, inserted.GetProperty("pricePence").GetInt64());

        // The republish that did the damage: a freshly minted Price at the engine's new decision.
        // PricePence is not assignable here, so accepting the pointer is accepting a £99.99 charge
        // behind a £49.00 card.
        var republished = await PublishAsync("pointer-contested", "price_second", 9999L);

        Assert.Equal("price_first", republished.GetProperty("providerPriceId").GetString());
        Assert.Equal(4900L, republished.GetProperty("pricePence").GetInt64());
    }

    [Fact]
    public async Task A_republish_carrying_the_same_price_id_is_untouched()
    {
        // The ordinary path, and the reason refusing a contested move costs nothing: bridge.py's
        // `_resolve_money_rail` reuses the pack's existing Price rather than minting per publish,
        // so a normal republish sends back the id already stored.
        await PublishAsync("pointer-same", "price_same", 4900L);
        var republished = await PublishAsync("pointer-same", "price_same", 4900L);

        Assert.Equal("price_same", republished.GetProperty("providerPriceId").GetString());
        Assert.Equal(4900L, republished.GetProperty("pricePence").GetInt64());
        Assert.True(republished.GetProperty("isListed").GetBoolean());
    }

    [Fact]
    public async Task A_stub_price_id_can_still_be_repaired_by_a_republish()
    {
        // `price_stub_*` is what bridge.py assigns when it cannot reach a payment rail. No checkout
        // can bill it, so there is no charge for a real id to contradict — and repairing those is
        // what tools/reprice_live_packs.py does THROUGH this endpoint. Closing the contested case
        // must not close this one.
        _factory.Payments.CanBill = false;
        var stubbed = await PublishAsync("pointer-stub", "price_stub_pointer", 4900L);
        Assert.Equal("price_stub_pointer", stubbed.GetProperty("providerPriceId").GetString());

        var repaired = await PublishAsync("pointer-stub", "price_real_now", 4900L);
        Assert.Equal("price_real_now", repaired.GetProperty("providerPriceId").GetString());
    }

    [Fact]
    public async Task An_omitted_price_id_still_does_not_null_the_stored_one()
    {
        // The 2026-08-08 guard this sits next to: omission must not null the pointer, or
        // FulfilmentService's product lookup fails and the buyer pays for a delivery that never
        // resolves. Asserted here too, because the new branch is the one that assigns it.
        await PublishAsync("pointer-omitted", "price_kept", 4900L);

        var body = Body("pointer-omitted", "price_kept", 4900L);
        body.Remove("providerPriceId");
        var response = await Client().PostAsJsonAsync("/internal/catalog", body);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);

        var after = await response.Content.ReadFromJsonAsync<JsonElement>();
        Assert.Equal("price_kept", after.GetProperty("providerPriceId").GetString());
    }
}
