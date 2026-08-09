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
/// write those columns was the /internal/catalog upsert, which on the update path assigned
/// ProviderProductId and ProviderPriceId unconditionally and never reassigns PricePence.
///
/// <see cref="Republishing_to_change_copy_no_longer_nulls_the_provider_ids"/> was written to
/// demonstrate that damage rather than assert it in a comment, so that it would FAIL the day the
/// publish route was made safe. On 2026-08-08 it did, and the guard it was waiting for landed
/// (Program.cs: the ids are now only overwritten when the request carried one). It is kept,
/// inverted, as the regression that stops the unconditional assignment coming back.
///
/// The endpoint still earns its place: a copy job routed through publish must re-send the entire
/// body, which re-runs the pricing ladder and the provisioner. This PATCH reaches copy and
/// nothing else.
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
    /// and the only endpoint that could reach that column was the upsert whose update path used to
    /// null the provider ids
    /// (see <see cref="Republishing_to_change_copy_no_longer_nulls_the_provider_ids"/>).
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

    /// <summary>
    /// The title is the whole shop window — shelf card, page H1, the <c>&lt;title&gt;</c> in a
    /// search result, the OG image on a shared link — and until 2026-08-09 it was written in
    /// exactly two places, both inside the upsert (Program.cs 466 and 480). ListingPatchRequest
    /// is <c>(bool IsListed, string Reason)</c> and reaches nothing else, so a pure copy edit to
    /// the most visible column on the storefront had to go through the endpoint this whole class
    /// exists to keep copy jobs away from. This is the narrow door for it.
    /// </summary>
    [Fact]
    public async Task Replaces_a_title_without_touching_the_money_rail()
    {
        await PublishAsync("copy-title");

        var response = await Client().PatchAsJsonAsync("/internal/catalog/copy-title/copy", new
        {
            title = "BandCheck, challenges a council tax band with the comparables",
        });

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var root = doc.RootElement;

        Assert.Equal("BandCheck, challenges a council tax band with the comparables",
            root.GetProperty("title").GetString());

        // The invariants this endpoint exists to protect, echoed back and asserted here so a
        // retitle job can never be the thing that unhooks a live pack from its price.
        Assert.Equal(4900L, root.GetProperty("pricePence").GetInt64());
        Assert.Equal(4900L, root.GetProperty("minBillablePence").GetInt64());
        Assert.Equal("price_real", root.GetProperty("providerPriceId").GetString());
        Assert.Equal("prod_real", root.GetProperty("providerProductId").GetString());
        Assert.True(root.GetProperty("isListed").GetBoolean());
        Assert.Equal("packs/copy-title/oldhash.zip", root.GetProperty("contentKey").GetString());
    }

    [Fact]
    public async Task Omitted_title_is_left_alone()
    {
        await PublishAsync("copy-title-omitted");

        var response = await Client().PatchAsJsonAsync("/internal/catalog/copy-title-omitted/copy",
            new { cardLine = "Only the card line is being set here." });

        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        Assert.Equal("Pack copy-title-omitted", doc.RootElement.GetProperty("title").GetString());
    }

    /// <summary>
    /// Title breaks the "" == clear rule for the same reason oneLine does: it is
    /// <c>required</c> on Pack (Store.Catalog/Domain/Pack.cs:6) with no fallback behind it, so a
    /// cleared value is a blank card, a blank H1 and an empty search result. A retitle job that
    /// sends "" by accident — a generator that returned nothing, say — must fail loudly rather
    /// than blank 48 live listings one PATCH at a time.
    /// </summary>
    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    public async Task Refuses_to_clear_a_title(string blank)
    {
        await PublishAsync("copy-title-blank");

        var response = await Client().PatchAsJsonAsync("/internal/catalog/copy-title-blank/copy",
            new { title = blank });

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);

        // And the live title is still there — the refusal is not merely a status code.
        var readback = await Client().PatchAsJsonAsync("/internal/catalog/copy-title-blank/copy",
            new { cardLine = "unrelated" });
        using var doc = JsonDocument.Parse(await readback.Content.ReadAsStringAsync());
        Assert.Equal("Pack copy-title-blank", doc.RootElement.GetProperty("title").GetString());
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
    /// The repair, pinned as a regression. This test was written inverted, to demonstrate the
    /// damage: a copy job routed through POST /internal/catalog has to re-send the whole publish
    /// body, the provider ids are returned by no GET projection so a backfill cannot echo them,
    /// and omitting them did not leave them alone — it NULLED them
    /// (<c>pack.ProviderProductId = request.ProviderProductId ?? request.PaddleProductId</c>).
    /// A null ProviderProductId breaks FulfilmentService's product lookup
    /// (<c>p.ProviderProductId == item.ProductId</c>): the buyer is charged and delivery never
    /// resolves.
    ///
    /// Program.cs now writes each id only when the request carried one, so omission is a no-op
    /// and the assertions below are the inverse of what they were.
    /// </summary>
    [Fact]
    public async Task Republishing_to_change_copy_no_longer_nulls_the_provider_ids()
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

        // The copy landed.
        Assert.Equal("New card line from the backfill", root.GetProperty("cardLine").GetString());

        // And the money rail survived it: an omitted id is "no change", not "clear".
        Assert.Equal("prod_real", root.GetProperty("providerProductId").GetString());
        Assert.Equal("price_real", root.GetProperty("providerPriceId").GetString());
        Assert.True(root.GetProperty("isListed").GetBoolean());

        // The provider label must not drift either. Nothing in that body named a provider, and
        // the legacy default is "paddle" — which on a pack holding price_* ids would describe a
        // rail that does not exist.
        Assert.Equal("stripe", root.GetProperty("paymentProvider").GetString());

        // Sending a DIFFERENT id still moves it: this guards omission, not change. Without this
        // the guard could be implemented as "never overwrite", which would strand every pack on
        // its first rail forever.
        var moved = await Client().PostAsJsonAsync("/internal/catalog", new Dictionary<string, object?>(StringComparer.Ordinal)
        {
            ["id"] = "copy-republish-hazard",
            ["title"] = "Pack copy-republish-hazard",
            ["oneLine"] = "One line.",
            ["dossierRef"] = "dossier:copy-republish-hazard",
            ["paymentProvider"] = "stripe",
            ["providerProductId"] = "prod_moved",
            ["providerPriceId"] = "price_moved",
            ["isListed"] = true,
        });
        using var movedDoc = JsonDocument.Parse(await moved.Content.ReadAsStringAsync());
        Assert.Equal("prod_moved", movedDoc.RootElement.GetProperty("providerProductId").GetString());
        Assert.Equal("price_moved", movedDoc.RootElement.GetProperty("providerPriceId").GetString());

        // The copy PATCH remains the narrow door, and still touches none of it.
        var patched = await Client().PatchAsJsonAsync(
            "/internal/catalog/copy-republish-hazard/copy",
            new { cardLine = "A second card line" });
        using var patchedDoc = JsonDocument.Parse(await patched.Content.ReadAsStringAsync());
        Assert.Equal("A second card line", patchedDoc.RootElement.GetProperty("cardLine").GetString());
        Assert.Equal("prod_moved", patchedDoc.RootElement.GetProperty("providerProductId").GetString());
        Assert.Equal("price_moved", patchedDoc.RootElement.GetProperty("providerPriceId").GetString());
        Assert.True(patchedDoc.RootElement.GetProperty("isListed").GetBoolean());
    }
}
