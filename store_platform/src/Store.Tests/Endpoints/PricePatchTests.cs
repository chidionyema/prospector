using System.Net;
using System.Net.Http.Json;
using System.Text.Json;

namespace Store.Tests.Endpoints;

/// <summary>
/// PATCH /internal/catalog/{id}/price (Program.cs PatchPackPrice) — the only writer of price.
/// </summary>
/// <remarks>
/// Two failures this guards. First, before this endpoint existed a published pack's price could
/// not be changed at all: /internal/catalog assigns PricePence on INSERT and silently omits it on
/// the update path, so a re-POST left the old price in place while returning 200. Second, the
/// obvious fix — one column, written carefully — strands paying buyers in both directions,
/// because fulfilment reads the catalogue while Stripe Checkout Sessions live up to 24h.
///
/// So the endpoint moves the price and the fulfilment floor together, and the floor is what these
/// tests care about. Wiring is tested here rather than as a pure function for the reason
/// StoreApiFactory exists: a rule tested apart from its wiring is how a fence ends up present in
/// the source and absent in production.
/// </remarks>
public sealed class PricePatchTests : IClassFixture<StoreApiFactory>
{
    private readonly StoreApiFactory _factory;

    public PricePatchTests(StoreApiFactory factory) => _factory = factory;

    private HttpClient Client(bool withKey = true)
    {
        var client = _factory.CreateClient();
        if (withKey) client.DefaultRequestHeaders.Add("X-Internal-Key", StoreApiFactory.InternalKey);
        return client;
    }

    private async Task PublishAsync(string id, long pricePence = 4900, bool listed = true)
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
            ["isListed"] = listed,
            ["contentKey"] = $"packs/{id}/hash.zip",
            ["contentHash"] = "hash",
        };
        var response = await Client().PostAsJsonAsync("/internal/catalog", body);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    private static object PatchBody(
        long pricePence,
        string? providerPriceId = "price_new",
        string? reason = "L1 ladder v1: b2b/part_time/us",
        string? actor = "price-engine") =>
        new { pricePence, providerPriceId, reason, actor, rationaleRef = "store/pricing/rationale/x.json" };

    private async Task<JsonElement> PatchAsync(string id, object body, HttpStatusCode expect = HttpStatusCode.OK)
    {
        var response = await Client().PatchAsJsonAsync($"/internal/catalog/{id}/price", body);
        Assert.Equal(expect, response.StatusCode);
        var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return doc.RootElement.Clone();
    }

    // --- the reason the endpoint exists at all ---

    [Fact]
    public async Task Changes_the_price_that_the_upsert_silently_refused_to_change()
    {
        await PublishAsync("pp-basic");

        var patched = await PatchAsync("pp-basic", PatchBody(7900));
        Assert.Equal(7900, patched.GetProperty("pricePence").GetInt64());

        // Read it back from the public catalogue, not the patch response: a 200 on a write proves
        // the handler ran, never that the value landed.
        var catalog = await Client(withKey: false).GetFromJsonAsync<JsonElement>("/catalog");
        var pack = catalog.EnumerateArray().Single(p => string.Equals(p.GetProperty("id").GetString(), "pp-basic", StringComparison.Ordinal));
        Assert.Equal("£79.00", pack.GetProperty("price").GetString());
    }

    [Fact]
    public async Task Repoints_the_provider_price_so_checkout_bills_the_new_amount()
    {
        await PublishAsync("pp-provider");

        var patched = await PatchAsync("pp-provider", PatchBody(7900, providerPriceId: "price_v2"));

        // Stripe Price objects are immutable, so a change means a new id. If the catalogue kept
        // the old one, checkout would build a session that bills the OLD amount while the
        // storefront shows the new one.
        Assert.Equal("price_v2", patched.GetProperty("providerPriceId").GetString());
    }

    // --- the floor: what stops a price change stranding a paying buyer ---

    [Fact]
    public async Task Cut_drops_the_floor_immediately()
    {
        await PublishAsync("pp-cut");

        var patched = await PatchAsync("pp-cut", PatchBody(2900));

        // No drain on a cut: the new price is already the minimum, so every live session clears
        // it. A buyer paying the new £29 must be served now, not in 26 hours.
        Assert.Equal(2900, patched.GetProperty("minBillablePence").GetInt64());
        Assert.True(patched.GetProperty("minBillableEffectiveAt").GetDateTime() <= DateTime.UtcNow.AddSeconds(5));
    }

    [Fact]
    public async Task Rise_holds_the_old_floor_and_schedules_it_to_close()
    {
        await PublishAsync("pp-rise");

        var patched = await PatchAsync("pp-rise", PatchBody(7900));

        // The floor stays at the old £49 while sessions minted at £49 can still be paid.
        Assert.Equal(7900, patched.GetProperty("pricePence").GetInt64());
        Assert.Equal(4900, patched.GetProperty("minBillablePence").GetInt64());
        Assert.True(
            patched.GetProperty("minBillableEffectiveAt").GetDateTime() > DateTime.UtcNow.AddHours(24),
            "the drain must outlast the 24h Checkout Session lifetime");
    }

    [Fact]
    public async Task Second_rise_inside_the_window_does_not_lift_the_floor_over_sessions_in_flight()
    {
        await PublishAsync("pp-double");

        await PatchAsync("pp-double", PatchBody(7900));
        var second = await PatchAsync("pp-double", PatchBody(9900));

        // Comparing against the CURRENT floor rather than against PricePence is the whole point:
        // against the price this would read 7900 and refuse every £49 session still unpaid.
        Assert.Equal(4900, second.GetProperty("minBillablePence").GetInt64());
    }

    // --- the guards ---

    [Fact]
    public async Task Rejects_an_unbillable_price_id_before_changing_anything()
    {
        await PublishAsync("pp-unbillable");
        _factory.Payments.CanBill = false;

        await PatchAsync("pp-unbillable", PatchBody(7900), HttpStatusCode.BadRequest);

        _factory.Payments.CanBill = true;
        var catalog = await Client(withKey: false).GetFromJsonAsync<JsonElement>("/catalog");
        var pack = catalog.EnumerateArray().Single(p => string.Equals(p.GetProperty("id").GetString(), "pp-unbillable", StringComparison.Ordinal));

        // The publish path already refuses to LIST a price the provider cannot bill. If the
        // re-price door did not clear the same bar it would be a way to walk a listed pack into
        // exactly the state publish rejects.
        Assert.Equal("£49.00", pack.GetProperty("price").GetString());
    }

    [Fact]
    public async Task Rejects_a_stub_price_id()
    {
        await PublishAsync("pp-stub");

        // What the engine mints when it cannot reach a real rail. Checkout builds a session from
        // whatever is stored, so a stub renders a buy button that 500s. bridge.py refuses to list
        // one; refuse to store one, on both ends of the wire.
        await PatchAsync(
            "pp-stub", PatchBody(7900, providerPriceId: "price_stub_abc123"), HttpStatusCode.BadRequest);
    }

    [Fact]
    public async Task Requires_a_reason_and_an_actor()
    {
        await PublishAsync("pp-why");

        // A price that moved with no stated cause is indistinguishable from a bug, and the next
        // person to look will move it back.
        await PatchAsync("pp-why", PatchBody(7900, reason: " "), HttpStatusCode.BadRequest);
        await PatchAsync("pp-why", PatchBody(7900, actor: " "), HttpStatusCode.BadRequest);
    }

    [Fact]
    public async Task Rejects_a_non_positive_price()
    {
        await PublishAsync("pp-zero");
        await PatchAsync("pp-zero", PatchBody(0), HttpStatusCode.BadRequest);
        await PatchAsync("pp-zero", PatchBody(-100), HttpStatusCode.BadRequest);
    }

    [Fact]
    public async Task Refuses_without_the_internal_key()
    {
        await PublishAsync("pp-auth");

        var response = await Client(withKey: false)
            .PatchAsJsonAsync("/internal/catalog/pp-auth/price", PatchBody(7900));

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Unknown_pack_is_404_not_a_silent_create()
    {
        var response = await Client().PatchAsJsonAsync("/internal/catalog/pp-nope/price", PatchBody(7900));
        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Fact]
    public async Task Touches_nothing_but_price()
    {
        await PublishAsync("pp-narrow");
        await PatchAsync("pp-narrow", PatchBody(7900));

        var catalog = await Client(withKey: false).GetFromJsonAsync<JsonElement>("/catalog");
        var pack = catalog.EnumerateArray().Single(p => string.Equals(p.GetProperty("id").GetString(), "pp-narrow", StringComparison.Ordinal));

        // Same narrow-door rule as the listing and content patches: re-pricing must not be able to
        // delist a pack, wipe its provider product, or repoint its deliverable.
        Assert.Equal("Pack pp-narrow", pack.GetProperty("title").GetString());
        Assert.Equal("stripe", pack.GetProperty("paymentProvider").GetString());
    }
}
