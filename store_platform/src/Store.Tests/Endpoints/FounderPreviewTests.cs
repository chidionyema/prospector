using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using Store.Api.Services;
using Store.Catalog.Domain;
using Store.Catalog.Domain.Identity;
using Store.Catalog.Persistence;

namespace Store.Tests.Endpoints;

/// <summary>
/// The founder preview reads any pack without a purchase — and nobody else may.
/// </summary>
/// <remarks>
/// The property under test is that the fence is an IDENTITY, not a credential. The rejected
/// design was an <c>X-Founder-Key</c> header: it passes every test you would write for it while
/// being transferable to anyone who reads a log. So the tests below all go through a real
/// registered, verified account and a real bearer token, and the discriminator is the address.
/// <para>
/// The three failure modes each get their own test because each of them ships silently: an
/// allowlist that is empty and therefore open, an address that was typed but never verified, and
/// a preview that quietly consumes a buyer's entitlement.
/// </para>
/// </remarks>
public sealed class FounderPreviewTests : IClassFixture<StoreApiFactory>
{
    private const string FounderEmail = "founder@example.com";
    private const string OutsiderEmail = "outsider@example.com";
    private const string PackId = "founderpreviewpack";
    private const string ContentKey = "packs/founderpreviewpack/deadbeef.zip";

    private readonly StoreApiFactory _factory;

    public FounderPreviewTests(StoreApiFactory factory) => _factory = factory;

    /// <summary>Records what it was asked to presign, so the test can assert the KEY, not just a 302.</summary>
    private sealed class RecordingStorage : IContentStorage
    {
        public bool IsConfigured { get; init; } = true;
        public string? LastKey { get; private set; }

        public Task<string> CreatePresignedGetUrlAsync(string objectKey, TimeSpan ttl)
        {
            LastKey = objectKey;
            return Task.FromResult($"https://r2.example/{objectKey}?sig=test");
        }
    }

    private WebApplicationFactory<Program> Host(string? allowlist, IContentStorage storage) =>
        _factory.WithWebHostBuilder(builder =>
        {
            // An absent allowlist is modelled as the setting never being written at all, which is
            // what a deploy that forgets the secret actually looks like.
            if (allowlist is not null)
            {
                builder.UseSetting("Founder:Emails", allowlist);
            }

            builder.ConfigureServices(services => services.AddSingleton(storage));
        });

    private static HttpClient NoRedirect(WebApplicationFactory<Program> host) =>
        host.CreateClient(new WebApplicationFactoryClientOptions { AllowAutoRedirect = false });

    /// <summary>Registers (once), verifies and logs in — a genuine bearer token, minted by the app.</summary>
    /// <remarks>
    /// Idempotent on purpose. Every <see cref="Host"/> in this class is a re-configured view of the
    /// SAME <see cref="StoreApiFactory"/>, so they all share one SQLite file — and the API refuses
    /// a second account on an address that is already registered (by design: orders join on the
    /// email string). A helper that blindly re-registered would silently fail on its second call
    /// and then fail to log in under a username that was never created. The username is therefore
    /// derived from the address rather than passed in, so one address is one account, always.
    /// </remarks>
    private static async Task<string> SignInAsync(WebApplicationFactory<Program> host, string email)
    {
        var user = email.Split('@')[0].Replace("-", string.Empty, StringComparison.Ordinal);
        var client = host.CreateClient();

        bool exists;
        using (var scope = host.Services.CreateScope())
        {
            var users = scope.ServiceProvider.GetRequiredService<UserManager<StoreUser>>();
            exists = await users.FindByEmailAsync(email) is not null;
        }

        if (!exists)
        {
            var registered = await client.PostAsJsonAsync("/v1/auth/register", new
            {
                username = user,
                email,
                password = "correct-horse-8",
                tos_version = "2026-07-31",
            });
            Assert.Equal(HttpStatusCode.OK, registered.StatusCode);

            using var scope = host.Services.CreateScope();
            var users = scope.ServiceProvider.GetRequiredService<UserManager<StoreUser>>();
            var account = await users.FindByEmailAsync(email);
            Assert.NotNull(account);
            var token = await users.GenerateEmailConfirmationTokenAsync(account!);
            var verified = await client.PostAsJsonAsync("/v1/auth/verify-email",
                new { user_id = account!.Id.ToString(), token });
            Assert.Equal(HttpStatusCode.OK, verified.StatusCode);
        }

        var login = await client.PostAsJsonAsync("/v1/auth/login",
            new { username = user, password = "correct-horse-8" });
        Assert.Equal(HttpStatusCode.OK, login.StatusCode);
        var jwt = (await login.Content.ReadFromJsonAsync<JsonElement>()).GetProperty("token").GetString();
        Assert.False(string.IsNullOrWhiteSpace(jwt));
        return jwt!;
    }

    private static async Task SeedPackAsync(WebApplicationFactory<Program> host, bool listed)
    {
        using var scope = host.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<StoreDbContext>();
        var existing = await db.Packs.FindAsync(PackId);
        if (existing is not null)
        {
            existing.IsListed = listed;
            existing.ContentKey = ContentKey;
        }
        else
        {
            db.Packs.Add(new Pack
            {
                Id = PackId,
                Title = "Fuel duty reclaim service for small fleet operators",
                OneLine = "Reclaims fuel duty for small fleets.",
                DossierRef = "dossiers/founderpreviewpack.json",
                PricePence = 4999,
                IsListed = listed,
                ContentKey = ContentKey,
            });
        }

        await db.SaveChangesAsync();
    }

    private static void Authorize(HttpClient client, string jwt) =>
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", jwt);

    [Fact]
    public async Task An_allowlisted_account_is_redirected_to_a_presigned_url_for_the_packs_current_bytes()
    {
        var storage = new RecordingStorage();
        var host = Host(FounderEmail, storage);
        await SeedPackAsync(host, listed: true);
        var jwt = await SignInAsync(host, FounderEmail);

        var client = NoRedirect(host);
        Authorize(client, jwt);
        var response = await client.GetAsync($"/v1/founder/packs/{PackId}/download");

        Assert.Equal(HttpStatusCode.Found, response.StatusCode);
        // The KEY, not merely a 302: a redirect to the wrong object is the defect that ships
        // one product's bytes under another product's name.
        Assert.Equal(ContentKey, storage.LastKey);
        Assert.Contains(ContentKey, response.Headers.Location!.ToString(), StringComparison.Ordinal);
    }

    [Fact]
    public async Task An_unlisted_pack_is_still_previewable()
    {
        // Deliberate. A pack delisted by a content gate is the one most worth reading, and
        // gating the preview on IsListed would hide exactly the failures it exists to inspect.
        var storage = new RecordingStorage();
        var host = Host(FounderEmail, storage);
        await SeedPackAsync(host, listed: false);
        var jwt = await SignInAsync(host, FounderEmail);

        var client = NoRedirect(host);
        Authorize(client, jwt);
        var response = await client.GetAsync($"/v1/founder/packs/{PackId}/download");

        Assert.Equal(HttpStatusCode.Found, response.StatusCode);
    }

    [Fact]
    public async Task The_preview_mints_no_entitlement_and_consumes_no_download_budget()
    {
        // The preview must not look like a sale in the numbers, and must not spend a real
        // buyer's capped download allowance on a pack the founder merely read.
        var host = Host(FounderEmail, new RecordingStorage());
        await SeedPackAsync(host, listed: true);
        var jwt = await SignInAsync(host, FounderEmail);

        var client = NoRedirect(host);
        Authorize(client, jwt);
        await client.GetAsync($"/v1/founder/packs/{PackId}/download");

        using var scope = host.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<StoreDbContext>();
        Assert.Empty(db.Entitlements.Where(e => e.PackId == PackId));
        Assert.Empty(db.Orders.Where(o => o.BuyerEmail == FounderEmail));
    }

    [Fact]
    public async Task A_signed_in_account_that_is_not_on_the_allowlist_gets_a_404()
    {
        var host = Host(FounderEmail, new RecordingStorage());
        await SeedPackAsync(host, listed: true);
        var jwt = await SignInAsync(host, OutsiderEmail);

        var client = NoRedirect(host);
        Authorize(client, jwt);
        var response = await client.GetAsync($"/v1/founder/packs/{PackId}/download");

        // 404 rather than 403: a stranger must not be able to confirm that the route exists or
        // that a given pack id is real.
        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Fact]
    public async Task An_empty_allowlist_grants_nobody_rather_than_everybody()
    {
        // The fail-open default is how a preview endpoint becomes a free-download hole the
        // first time a deploy forgets its secret. Both spellings of "absent" are covered.
        var host = Host(allowlist: null, storage: new RecordingStorage());
        await SeedPackAsync(host, listed: true);
        var jwt = await SignInAsync(host, FounderEmail);

        var client = NoRedirect(host);
        Authorize(client, jwt);
        Assert.Equal(HttpStatusCode.NotFound,
            (await client.GetAsync($"/v1/founder/packs/{PackId}/download")).StatusCode);

        var blank = Host("   ", new RecordingStorage());
        var blankClient = NoRedirect(blank);
        Authorize(blankClient, jwt);
        Assert.Equal(HttpStatusCode.NotFound,
            (await blankClient.GetAsync($"/v1/founder/packs/{PackId}/download")).StatusCode);
    }

    [Fact]
    public async Task An_unverified_account_on_the_allowlist_is_refused()
    {
        // The allowlist is a list of ADDRESSES; an unverified address was typed, not proven.
        // Honouring one would make the fence forgeable by anyone who can spell it.
        var host = Host("unverified@example.com", new RecordingStorage());
        await SeedPackAsync(host, listed: true);

        var client = host.CreateClient();
        await client.PostAsJsonAsync("/v1/auth/register", new
        {
            username = "unverifiedfounder",
            email = "unverified@example.com",
            password = "correct-horse-8",
            tos_version = "2026-07-31",
        });

        // Login itself is refused before verification, so there is no token to present — which
        // is the fence holding, one layer earlier. Asserted so a future change that issues
        // tokens pre-verification cannot open this endpoint as a side effect.
        var login = await client.PostAsJsonAsync("/v1/auth/login",
            new { username = "unverifiedfounder", password = "correct-horse-8" });
        Assert.Equal(HttpStatusCode.Unauthorized, login.StatusCode);

        // And unauthenticated, the endpoint answers 401 rather than serving anything.
        var anonymous = await NoRedirect(host).GetAsync($"/v1/founder/packs/{PackId}/download");
        Assert.Equal(HttpStatusCode.Unauthorized, anonymous.StatusCode);
    }

    [Fact]
    public async Task The_allowlist_match_ignores_case_and_surrounding_whitespace()
    {
        // Mailbox case is not significant at any provider the store trusts, and a secret pasted
        // with a stray space is the most likely way this fence fails in production.
        var storage = new RecordingStorage();
        var host = Host($" Founder@Example.COM , someone-else@example.com ", storage);
        await SeedPackAsync(host, listed: true);
        var jwt = await SignInAsync(host, FounderEmail);

        var client = NoRedirect(host);
        Authorize(client, jwt);
        Assert.Equal(HttpStatusCode.Found,
            (await client.GetAsync($"/v1/founder/packs/{PackId}/download")).StatusCode);
    }

    [Fact]
    public async Task Storage_being_down_is_a_503_not_a_404()
    {
        // An operator-visible failure must not read as "that pack does not exist", which is how
        // an outage gets diagnosed as a data problem.
        var host = Host(FounderEmail, new RecordingStorage { IsConfigured = false });
        await SeedPackAsync(host, listed: true);
        var jwt = await SignInAsync(host, FounderEmail);

        var client = NoRedirect(host);
        Authorize(client, jwt);
        var response = await client.GetAsync($"/v1/founder/packs/{PackId}/download");

        Assert.Equal(HttpStatusCode.ServiceUnavailable, response.StatusCode);
    }

    [Fact]
    public async Task The_storefront_can_ask_whether_this_account_is_the_founder()
    {
        // Without this, the only way for the web to decide whether to render the affordance is
        // to attempt a download and read a 404 — indistinguishable from a missing pack.
        var host = Host(FounderEmail, new RecordingStorage());
        var founderJwt = await SignInAsync(host, FounderEmail);
        var outsiderJwt = await SignInAsync(host, OutsiderEmail);

        var asFounder = host.CreateClient();
        Authorize(asFounder, founderJwt);
        Assert.True((await asFounder.GetFromJsonAsync<JsonElement>("/v1/founder/me"))
            .GetProperty("founder").GetBoolean());

        var asOutsider = host.CreateClient();
        Authorize(asOutsider, outsiderJwt);
        Assert.False((await asOutsider.GetFromJsonAsync<JsonElement>("/v1/founder/me"))
            .GetProperty("founder").GetBoolean());
    }
}
