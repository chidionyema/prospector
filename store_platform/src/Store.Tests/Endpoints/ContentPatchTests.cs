using System.Net;
using System.Net.Http.Json;
using System.Text.Json;

namespace Store.Tests.Endpoints;

/// <summary>
/// PATCH /internal/catalog/{id}/content (Program.cs PatchPackContent) — the narrow door that
/// repoints a pack's content-addressed deliverable and can reach nothing else.
/// </summary>
/// <remarks>
/// The failure this guards: content keys are packs/&lt;id&gt;/&lt;sha256&gt;.zip, so ANY bundle
/// change mints a new object key, and the only other way to repoint a listing is the
/// /internal/catalog upsert — which assigns title, provider ids and listing state
/// unconditionally. A formatting backfill must be able to swap the zip without ever holding
/// the power to break the money rail.
/// </remarks>
public sealed class ContentPatchTests : IClassFixture<StoreApiFactory>
{
    private readonly StoreApiFactory _factory;

    public ContentPatchTests(StoreApiFactory factory) => _factory = factory;

    private HttpClient Client(bool withKey = true)
    {
        var client = _factory.CreateClient();
        if (withKey) client.DefaultRequestHeaders.Add("X-Internal-Key", StoreApiFactory.InternalKey);
        return client;
    }

    private async Task PublishAsync(string id, bool withContent = true)
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
            ["isListed"] = withContent,
        };
        if (withContent)
        {
            body["contentKey"] = $"packs/{id}/oldhash.zip";
            body["contentHash"] = "oldhash";
        }

        var response = await Client().PostAsJsonAsync("/internal/catalog", body);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    private static object PatchBody(string id, string hash = "newhash", string? reason = "index.html backfill 2026-07-31") =>
        new { contentKey = $"packs/{id}/{hash}.zip", contentHash = hash, reason };

    [Fact]
    public async Task Repoints_content_and_bumps_version_without_touching_anything_else()
    {
        await PublishAsync("cp-repoint");

        var response = await Client().PatchAsJsonAsync(
            "/internal/catalog/cp-repoint/content", PatchBody("cp-repoint"));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        Assert.Equal("packs/cp-repoint/newhash.zip", doc.RootElement.GetProperty("contentKey").GetString());
        Assert.Equal("newhash", doc.RootElement.GetProperty("contentHash").GetString());
        Assert.Equal(2, doc.RootElement.GetProperty("contentVersion").GetInt32());

        // The pack is still live and its sales surface untouched — the whole point of the door.
        var details = await _factory.CreateClient().GetAsync("/catalog/cp-repoint");
        Assert.Equal(HttpStatusCode.OK, details.StatusCode);
        using var page = JsonDocument.Parse(await details.Content.ReadAsStringAsync());
        Assert.Equal("Pack cp-repoint", page.RootElement.GetProperty("title").GetString());
        Assert.Equal("price_real", page.RootElement.GetProperty("providerPriceId").GetString());
    }

    [Fact]
    public async Task Rejects_a_key_that_is_not_this_packs_content_addressed_path()
    {
        await PublishAsync("cp-crosswire");
        await PublishAsync("cp-victim");

        // Pointing cp-crosswire's download at cp-victim's object must be unrepresentable.
        var response = await Client().PatchAsJsonAsync(
            "/internal/catalog/cp-crosswire/content",
            new { contentKey = "packs/cp-victim/newhash.zip", contentHash = "newhash", reason = "x" });

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Rejects_a_hash_that_does_not_match_the_key()
    {
        await PublishAsync("cp-hash-mismatch");

        var response = await Client().PatchAsJsonAsync(
            "/internal/catalog/cp-hash-mismatch/content",
            new { contentKey = "packs/cp-hash-mismatch/aaa.zip", contentHash = "bbb", reason = "x" });

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Refuses_to_grant_first_time_content()
    {
        // Registered UNLISTED with no deliverable: repointing must not become a side door past
        // the list-only-after-upload gate in /internal/catalog.
        await PublishAsync("cp-no-content", withContent: false);

        var response = await Client().PatchAsJsonAsync(
            "/internal/catalog/cp-no-content/content", PatchBody("cp-no-content"));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Requires_a_reason()
    {
        await PublishAsync("cp-no-reason");

        var response = await Client().PatchAsJsonAsync(
            "/internal/catalog/cp-no-reason/content", PatchBody("cp-no-reason", reason: ""));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Rejects_a_missing_or_wrong_internal_key()
    {
        await PublishAsync("cp-auth");

        var noKey = await Client(withKey: false).PatchAsJsonAsync(
            "/internal/catalog/cp-auth/content", PatchBody("cp-auth"));
        Assert.Equal(HttpStatusCode.Unauthorized, noKey.StatusCode);

        var wrongKey = _factory.CreateClient();
        wrongKey.DefaultRequestHeaders.Add("X-Internal-Key", "not-the-key");
        var wrong = await wrongKey.PatchAsJsonAsync(
            "/internal/catalog/cp-auth/content", PatchBody("cp-auth"));
        Assert.Equal(HttpStatusCode.Unauthorized, wrong.StatusCode);
    }

    [Fact]
    public async Task Unknown_pack_is_404()
    {
        var response = await Client().PatchAsJsonAsync(
            "/internal/catalog/cp-ghost/content", PatchBody("cp-ghost"));

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }
}
