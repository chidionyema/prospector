using System.Net;
using System.Net.Http.Json;
using System.Text.Json;

namespace Store.Tests.Endpoints;

/// <summary>
/// PATCH /internal/catalog/{id}/copy (Program.cs PatchPackCopy) — the narrow door that replaces
/// a live pack's storefront copy and can reach nothing else.
/// </summary>
/// <remarks>
/// The failure this guards, measured on the live catalogue 2026-08-06: 45 of 61 live packs had
/// no listing_page artifact on their dossier, so the storefront was showing pack_floors'
/// deterministic floor — headline == title on 34, no cardLine on 55, proofPoint a raw check
/// rationale on 28. Replacing that copy is a pure content job, but the only endpoint that could
/// write those columns was the /internal/catalog upsert, which on the update path assigns
/// ProviderProductId and ProviderPriceId unconditionally and never reassigns PricePence.
///
/// <see cref="Republishing_to_change_copy_nulls_the_provider_ids"/> is the test that earns this
/// endpoint: it demonstrates the damage on the publish route rather than asserting it in a
/// comment, so if that route is ever made safe this test fails and tells us so.
/// </remarks>
public sealed class CopyPatchTests : IClassFixture<StoreApiFactory>
{
    private readonly StoreApiFactory _factory;

    // CA1861: these are passed to PatchAsJsonAsync repeatedly and never mutated.
    private static readonly string[] TwoDeliverables = ["Blueprint", "Go-to-market plan"];
    private static readonly string[] OneDeliverable = ["Blueprint"];

    public CopyPatchTests(StoreApiFactory factory) => _factory = factory;

    private HttpClient Client(bool withKey = true)
    {
        var client = _factory.CreateClient();
        if (withKey) client.DefaultRequestHeaders.Add("X-Internal-Key", StoreApiFactory.InternalKey);
        return client;
    }

    /// <summary>Publishes a pack carrying the floor copy the backfill is meant to replace.</summary>
    private async Task PublishAsync(string id)
    {
        _factory.Payments.CanBill = true;
        var body = new Dictionary<string, object?>(StringComparer.Ordinal)
        {
            ["id"] = id,
            ["title"] = $"Pack {id}",
            ["oneLine"] = "One line.",
            ["dossierRef"] = $"dossier:{id}",
            ["paymentProvider"] = "stripe",
            ["providerProductId"] = "prod_real",
            ["providerPriceId"] = "price_real",
            ["pricePence"] = 4900L,
            ["isListed"] = true,
            ["contentKey"] = $"packs/{id}/oldhash.zip",
            ["contentHash"] = "oldhash",
            // The floor: headline is the title verbatim, no card line at all.
            ["headline"] = $"Pack {id}",
            ["proofPoint"] = "buyer intent: One passage shows an active audience.",
        };

        var response = await Client().PostAsJsonAsync("/internal/catalog", body);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [Fact]
    public async Task Replaces_copy_without_touching_price_provider_ids_or_listing_state()
    {
        await PublishAsync("copy-replace");

        var response = await Client().PatchAsJsonAsync("/internal/catalog/copy-replace/copy", new
        {
            cardLine = "Books vetted respite carers for family caregivers",
            headline = "Launch a service that gets carers paid for the respite they already take",
            subhead = "A verified opportunity with a costed build plan.",
            proofPoint = "VOA figures show 57% of firms that challenge secure a reduction.",
            whatYouGet = TwoDeliverables,
        });

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var root = doc.RootElement;

        // The copy moved.
        Assert.Equal("Books vetted respite carers for family caregivers", root.GetProperty("cardLine").GetString());
        Assert.Equal("Launch a service that gets carers paid for the respite they already take",
            root.GetProperty("headline").GetString());
        Assert.Equal("A verified opportunity with a costed build plan.", root.GetProperty("subhead").GetString());
        Assert.Equal(2, root.GetProperty("whatYouGet").GetArrayLength());

        // Nothing that decides what a buyer is charged, or whether they can be, moved with it.
        Assert.Equal(4900L, root.GetProperty("pricePence").GetInt64());
        Assert.Equal(4900L, root.GetProperty("minBillablePence").GetInt64());
        Assert.Equal("price_real", root.GetProperty("providerPriceId").GetString());
        Assert.Equal("prod_real", root.GetProperty("providerProductId").GetString());
        Assert.True(root.GetProperty("isListed").GetBoolean());
        Assert.Equal("packs/copy-replace/oldhash.zip", root.GetProperty("contentKey").GetString());
    }

    [Fact]
    public async Task Omitted_field_is_left_alone_and_empty_string_clears_it()
    {
        await PublishAsync("copy-null-vs-empty");

        // Establish a card line, then send a patch that omits it entirely.
        await Client().PatchAsJsonAsync("/internal/catalog/copy-null-vs-empty/copy",
            new { cardLine = "Original card line" });

        var untouched = await Client().PatchAsJsonAsync("/internal/catalog/copy-null-vs-empty/copy",
            new { subhead = "Only the subhead is being set here." });
        using (var doc = JsonDocument.Parse(await untouched.Content.ReadAsStringAsync()))
        {
            Assert.Equal("Original card line", doc.RootElement.GetProperty("cardLine").GetString());
        }

        // "" is the escape hatch: without it, copy written in error could never be withdrawn
        // through this endpoint, because null already means "no change".
        var cleared = await Client().PatchAsJsonAsync("/internal/catalog/copy-null-vs-empty/copy",
            new { cardLine = "" });
        using (var doc = JsonDocument.Parse(await cleared.Content.ReadAsStringAsync()))
        {
            Assert.Equal(JsonValueKind.Null, doc.RootElement.GetProperty("cardLine").ValueKind);
        }
    }

    [Fact]
    public async Task Empty_array_clears_a_list_field()
    {
        await PublishAsync("copy-empty-list");

        await Client().PatchAsJsonAsync("/internal/catalog/copy-empty-list/copy",
            new { whatYouGet = OneDeliverable });

        var response = await Client().PatchAsJsonAsync("/internal/catalog/copy-empty-list/copy",
            new { whatYouGet = Array.Empty<string>() });

        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        Assert.Equal(0, doc.RootElement.GetProperty("whatYouGet").GetArrayLength());
    }

    /// <summary>
    /// The repair this field was added for.
    ///
    /// <c>bridge.py</c> cut <c>oneLine</c> at a character index (<c>one_liner[:150] + "..."</c>)
    /// until 2026-08-06. Measured against the live catalogue that day: 34 of the 63 listed packs
    /// were exactly 153 characters and 32 of those ended part-way through a word — "for a flat fee
    /// per applicat...". That string is the card description AND the lead paragraph above the buy
    /// button. Fixing the engine stops the 35th; it does not touch the 34 already in the database,
    /// and the only endpoint that could reach that column was the upsert whose update path nulls
    /// the provider ids (see <see cref="Republishing_to_change_copy_nulls_the_provider_ids"/>).
    /// </summary>
    [Fact]
    public async Task Replaces_a_truncated_one_line_without_touching_the_money_rail()
    {
        await PublishAsync("copy-oneline");

        var response = await Client().PatchAsJsonAsync("/internal/catalog/copy-oneline/copy", new
        {
            oneLine = "Files the council tax band challenge, with the comparables that decide it…",
        });

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var root = doc.RootElement;

        Assert.Equal("Files the council tax band challenge, with the comparables that decide it…",
            root.GetProperty("oneLine").GetString());

        Assert.Equal(4900L, root.GetProperty("pricePence").GetInt64());
        Assert.Equal(4900L, root.GetProperty("minBillablePence").GetInt64());
        Assert.Equal("price_real", root.GetProperty("providerPriceId").GetString());
        Assert.Equal("prod_real", root.GetProperty("providerProductId").GetString());
        Assert.True(root.GetProperty("isListed").GetBoolean());
        Assert.Equal("packs/copy-oneline/oldhash.zip", root.GetProperty("contentKey").GetString());
    }

    [Fact]
    public async Task Omitted_one_line_is_left_alone()
    {
        await PublishAsync("copy-oneline-omitted");

        var response = await Client().PatchAsJsonAsync("/internal/catalog/copy-oneline-omitted/copy",
            new { cardLine = "Only the card line is being set here." });

        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        Assert.Equal("One line.", doc.RootElement.GetProperty("oneLine").GetString());
    }

    /// <summary>
    /// oneLine breaks the "" == clear rule the rest of this endpoint follows, on purpose.
    ///
    /// Pack.OneLine is <c>required</c> and is printed by the catalogue card, the pack page lead
    /// paragraph, the basket line and llms.txt. There is no fallback behind it, so a cleared value
    /// is blank space directly above the buy button — and a repair job that sends the empty string
    /// by accident (a dossier read that returned nothing, say) would silently blank a live listing
    /// rather than fail. The endpoint may improve a description; it may not delete one.
    /// </summary>
    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    public async Task Refuses_to_clear_one_line(string blank)
    {
        await PublishAsync("copy-oneline-blank");

        var response = await Client().PatchAsJsonAsync("/internal/catalog/copy-oneline-blank/copy",
            new { oneLine = blank });

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);

        // And the live description is still there — the refusal is not merely a status code.
        var readback = await Client().PatchAsJsonAsync("/internal/catalog/copy-oneline-blank/copy",
            new { cardLine = "unrelated" });
        using var doc = JsonDocument.Parse(await readback.Content.ReadAsStringAsync());
        Assert.Equal("One line.", doc.RootElement.GetProperty("oneLine").GetString());
    }

    [Fact]
    public async Task Rejects_a_request_without_the_internal_key()
    {
        await PublishAsync("copy-unauthorised");

        var response = await Client(withKey: false).PatchAsJsonAsync(
            "/internal/catalog/copy-unauthorised/copy", new { cardLine = "should not land" });

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Returns_404_for_a_pack_that_does_not_exist()
    {
        var response = await Client().PatchAsJsonAsync(
            "/internal/catalog/copy-no-such-pack/copy", new { cardLine = "x" });

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    /// <summary>
    /// The reason this endpoint exists, demonstrated rather than asserted.
    ///
    /// A copy job routed through POST /internal/catalog has to re-send the whole publish body.
    /// The provider ids are not returned by any GET projection, so a backfill cannot read them
    /// back to echo them — and omitting them does not leave them alone, it NULLS them
    /// (Program.cs: <c>pack.ProviderProductId = request.ProviderProductId ?? request.PaddleProductId</c>).
    /// A null ProviderProductId breaks FulfilmentService's product lookup
    /// (<c>p.ProviderProductId == item.ProductId</c>): the buyer is charged and delivery never
    /// resolves.
    /// </summary>
    [Fact]
    public async Task Republishing_to_change_copy_nulls_the_provider_ids()
    {
        await PublishAsync("copy-republish-hazard");
        _factory.Payments.CanBill = true;

        // Exactly what a copy backfill would send if it went through publish: the required
        // fields plus the new copy, with no provider ids because it cannot read them.
        var response = await Client().PostAsJsonAsync("/internal/catalog", new Dictionary<string, object?>(StringComparer.Ordinal)
        {
            ["id"] = "copy-republish-hazard",
            ["title"] = "Pack copy-republish-hazard",
            ["oneLine"] = "One line.",
            ["dossierRef"] = "dossier:copy-republish-hazard",
            ["isListed"] = true,
            ["cardLine"] = "New card line from the backfill",
        });

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var root = doc.RootElement;

        // The copy landed — which is exactly why this route looks like it worked.
        Assert.Equal("New card line from the backfill", root.GetProperty("cardLine").GetString());

        // And the money rail is now broken, silently.
        Assert.Equal(JsonValueKind.Null, root.GetProperty("providerProductId").ValueKind);
        Assert.Equal(JsonValueKind.Null, root.GetProperty("providerPriceId").ValueKind);

        // What happens to the listing from here depends on the payment provider, and both
        // outcomes are broken, so this test asserts neither. A real Stripe answers
        // CanBillPriceAsync("") false and the pack drops out of the catalogue; FakePaymentProvider
        // returns its CanBill flag without looking at the id (FakePaymentProvider.cs:54-57), so
        // here the pack stays listed with unresolvable provider ids — sellable and unfulfillable.
        // Asserting either value would be asserting the fake, not the endpoint.

        // The copy PATCH, given the same job, does none of that.
        await PublishAsync("copy-republish-hazard");
        var patched = await Client().PatchAsJsonAsync(
            "/internal/catalog/copy-republish-hazard/copy",
            new { cardLine = "New card line from the backfill" });
        using var patchedDoc = JsonDocument.Parse(await patched.Content.ReadAsStringAsync());
        Assert.Equal("New card line from the backfill", patchedDoc.RootElement.GetProperty("cardLine").GetString());
        Assert.Equal("prod_real", patchedDoc.RootElement.GetProperty("providerProductId").GetString());
        Assert.Equal("price_real", patchedDoc.RootElement.GetProperty("providerPriceId").GetString());
        Assert.True(patchedDoc.RootElement.GetProperty("isListed").GetBoolean());
    }
}
