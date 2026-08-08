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
    public async Task Read_endpoint_returns_the_current_pointer_and_tracks_a_repoint()
    {
        await PublishAsync("cp-read");

        var before = await Client().GetAsync("/internal/catalog/cp-read/content");
        Assert.Equal(HttpStatusCode.OK, before.StatusCode);
        using (var doc = JsonDocument.Parse(await before.Content.ReadAsStringAsync()))
        {
            Assert.Equal("packs/cp-read/oldhash.zip", doc.RootElement.GetProperty("contentKey").GetString());
        }

        var patch = await Client().PatchAsJsonAsync("/internal/catalog/cp-read/content", PatchBody("cp-read"));
        Assert.Equal(HttpStatusCode.OK, patch.StatusCode);

        var after = await Client().GetAsync("/internal/catalog/cp-read/content");
        using (var doc = JsonDocument.Parse(await after.Content.ReadAsStringAsync()))
        {
            Assert.Equal("packs/cp-read/newhash.zip", doc.RootElement.GetProperty("contentKey").GetString());
            Assert.Equal(2, doc.RootElement.GetProperty("contentVersion").GetInt32());
        }
    }

    /// <summary>
    /// The version counter belongs to the server, and this is the case that proves why.
    ///
    /// contentVersion is returned by no public GET projection, so a republishing engine cannot
    /// read the current value to increment it. bridge.py computed <c>(missing ?? 0) + 1</c> and
    /// sent 1 on every republish — knocking a pack on its fourth revision back to its first.
    /// FulfilmentService stamps that number onto the buyer's record, so a reset makes one version
    /// describe two different bundles. The engine now omits the field and the upsert counts.
    /// </summary>
    [Fact]
    public async Task Republishing_new_content_bumps_the_version_without_being_told_the_number()
    {
        await PublishAsync("cp-server-owned");           // version 1, hash "oldhash"

        // A republish carrying new content and NO contentVersion, exactly as the engine sends it.
        await RepublishAsync("cp-server-owned", "hash-v2");
        Assert.Equal(2, await VersionAsync("cp-server-owned"));

        await RepublishAsync("cp-server-owned", "hash-v3");
        Assert.Equal(3, await VersionAsync("cp-server-owned"));

        // Unchanged content is not a new version — a copy-only republish must not inflate it.
        await RepublishAsync("cp-server-owned", "hash-v3");
        Assert.Equal(3, await VersionAsync("cp-server-owned"));
    }

    [Fact]
    public async Task An_explicitly_sent_version_still_wins()
    {
        await PublishAsync("cp-explicit-version");
        await RepublishAsync("cp-explicit-version", "hash-v2", version: 47);
        Assert.Equal(47, await VersionAsync("cp-explicit-version"));
    }

    [Fact]
    public async Task A_brand_new_pack_starts_at_version_one_not_two()
    {
        await PublishAsync("cp-first-publish");
        Assert.Equal(1, await VersionAsync("cp-first-publish"));
    }

    private async Task RepublishAsync(string id, string hash, int? version = null)
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
            ["isListed"] = true,
            ["contentKey"] = $"packs/{id}/{hash}.zip",
            ["contentHash"] = hash,
        };
        if (version is { } v) body["contentVersion"] = v;

        var response = await Client().PostAsJsonAsync("/internal/catalog", body);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    private async Task<int> VersionAsync(string id)
    {
        var response = await Client().GetAsync($"/internal/catalog/{id}/content");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return doc.RootElement.GetProperty("contentVersion").GetInt32();
    }

    [Fact]
    public async Task Read_endpoint_requires_the_internal_key()
    {
        await PublishAsync("cp-read-auth");

        var response = await Client(withKey: false).GetAsync("/internal/catalog/cp-read-auth/content");
        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Unknown_pack_is_404()
    {
        var response = await Client().PatchAsJsonAsync(
            "/internal/catalog/cp-ghost/content", PatchBody("cp-ghost"));

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }
}
