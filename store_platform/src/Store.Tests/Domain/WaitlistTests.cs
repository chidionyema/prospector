using System.Net;
using System.Threading.RateLimiting;
using Microsoft.AspNetCore.Http;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using Store.Api.Contracts;
using Store.Api.Infrastructure;
using Store.Api.Services;
using Store.Catalog.Persistence;

namespace Store.Tests.Domain;

/// <summary>
/// The waitlist is the only unauthenticated endpoint that writes personal data, so its rules
/// are legal gates rather than polish: consent is validated server-side, the consent evidence
/// is what the server hashed rather than what the client claimed, the IP is never stored raw,
/// and the endpoint is throttled hard without touching the webhook exemption.
///
/// Real SQLite (in memory, not the EF InMemory provider) so the schema constraints in
/// StoreDbContext are actually exercised, matching the pattern in FulfilmentServiceTests.
/// </summary>
public sealed class WaitlistTests : IDisposable
{
    private const string ConsentText =
        "Email me if a pack in this space survives the six checks. One email, only if a pack ships.";

    private const string Salt = "test-salt-not-a-real-secret";

    private readonly SqliteConnection _connection;
    private readonly DbContextOptions<StoreDbContext> _options;

    public WaitlistTests()
    {
        _connection = new SqliteConnection("Filename=:memory:");
        _connection.Open();
        _options = new DbContextOptionsBuilder<StoreDbContext>()
            .UseSqlite(_connection)
            .Options;

        using var db = new StoreDbContext(_options);
        db.Database.EnsureCreated();
    }

    public void Dispose() => _connection.Dispose();

    private StoreDbContext NewDb() => new(_options);

    // AC-17 — submitting with the consent box unticked is rejected server-side. The browser
    // also blocks it, but a UI control is an affordance, not a gate: the request can be made
    // by hand, and consent that was not given cannot be inferred from a request arriving.
    [Fact]
    public async Task Rejects_MissingConsent()
    {
        await using var db = NewDb();
        var service = new WaitlistService(db, Salt);

        var result = await service.SignUpAsync(
            new WaitlistRequest("someone@example.com", Consent: false, ConsentText), "203.0.113.7");

        Assert.False(result.Succeeded);
        Assert.Contains("consent", result.Error!, StringComparison.OrdinalIgnoreCase);
        Assert.Empty(await db.WaitlistSignups.ToListAsync());
    }

    // AC-18 — a stored signup carries the consent version, a hash of the exact wording shown,
    // a hashed IP, and the originating query. The raw address is never persisted.
    [Fact]
    public async Task Persists_ConsentEvidence_AndHashesIp()
    {
        const string ip = "203.0.113.7";
        await using var db = NewDb();
        var service = new WaitlistService(db, Salt);

        var result = await service.SignUpAsync(
            new WaitlistRequest(
                "someone@example.com",
                Consent: true,
                ConsentText,
                Query: "AI for dentists",
                Source: "catalog-empty-state"),
            ip);

        Assert.True(result.Succeeded);

        var stored = Assert.Single(await db.WaitlistSignups.ToListAsync());
        Assert.Equal("someone@example.com", stored.Email);
        Assert.Equal("AI for dentists", stored.Query);
        Assert.Equal("catalog-empty-state", stored.Source);
        Assert.Equal(WaitlistService.CurrentConsentVersion, stored.ConsentVersion);

        // The hash is of the exact sentence shown — recomputable, and therefore checkable
        // against the wording a year from now.
        Assert.Equal(WaitlistService.HashConsentText(ConsentText), stored.ConsentTextHash);
        Assert.Equal(64, stored.ConsentTextHash.Length);  // SHA-256, hex

        // The IP is present as a salted hash and absent as an address.
        Assert.NotNull(stored.IpHash);
        Assert.Equal(64, stored.IpHash!.Length);
        Assert.DoesNotContain(ip, stored.IpHash, StringComparison.Ordinal);

        // And the salt is doing work: the same address under a different salt is a different
        // hash, so a leaked table is not a rainbow-table lookup of the whole IPv4 space.
        Assert.NotEqual(WaitlistService.HashIp(ip, "another-salt"), stored.IpHash);
        Assert.Equal(WaitlistService.HashIp(ip, Salt), stored.IpHash);
    }

    [Fact]
    public void HashConsentText_IsSensitiveToTheWording()
    {
        // If the sentence changes by one word, the evidence must show a different hash —
        // otherwise "we can prove what they agreed to" is not true.
        Assert.NotEqual(
            WaitlistService.HashConsentText(ConsentText),
            WaitlistService.HashConsentText(ConsentText.Replace("only if", "when", StringComparison.Ordinal)));
    }

    [Fact]
    public void HashIp_NullIn_NullOut()
    {
        // A request with no resolvable address stores no address. Hashing the literal string
        // "unknown" would collide every such caller into one bucket that looks like a real
        // identity in the data.
        Assert.Null(WaitlistService.HashIp(null, Salt));
        Assert.Null(WaitlistService.HashIp("", Salt));
    }

    [Theory]
    [InlineData("")]
    [InlineData("not-an-email")]
    [InlineData("no@domain")]
    [InlineData("two@at@signs.com")]
    [InlineData("spaces in@example.com")]
    public async Task Rejects_MalformedEmail_BeforeWriting(string email)
    {
        await using var db = NewDb();
        var service = new WaitlistService(db, Salt);

        var result = await service.SignUpAsync(
            new WaitlistRequest(email, Consent: true, ConsentText), "203.0.113.7");

        Assert.False(result.Succeeded);
        Assert.Empty(await db.WaitlistSignups.ToListAsync());
    }

    [Fact]
    public async Task Rejects_EmptyConsentText_BecauseThereWouldBeNoEvidence()
    {
        await using var db = NewDb();
        var service = new WaitlistService(db, Salt);

        var result = await service.SignUpAsync(
            new WaitlistRequest("someone@example.com", Consent: true, ConsentText: "   "), null);

        Assert.False(result.Succeeded);
        Assert.Empty(await db.WaitlistSignups.ToListAsync());
    }

    [Fact]
    public async Task SameEmail_MayJoinTwice_ForDifferentGaps()
    {
        // Not a unique index by design: one person may legitimately ask about two different
        // spaces, and each ask carries its own consent evidence and its own demand signal.
        await using var db = NewDb();
        var service = new WaitlistService(db, Salt);

        await service.SignUpAsync(
            new WaitlistRequest("someone@example.com", true, ConsentText, Query: "dentists"), null);
        await service.SignUpAsync(
            new WaitlistRequest("someone@example.com", true, ConsentText, Query: "plumbers"), null);

        Assert.Equal(2, await db.WaitlistSignups.CountAsync());
    }

    // AC-19 — 429 after 5 requests in a minute from one IP, and /webhooks stays exempt.
    //
    // This drives the real PartitionedRateLimiter that Program.cs installs as its global
    // limiter (RateLimitPolicy.Create is the one construction site), against hand-built
    // HttpContexts. It proves the policy, not the middleware: the middleware is ASP.NET's own
    // UseRateLimiter, wired at Program.cs with no custom logic between it and this object.
    [Fact]
    public void RateLimits_PerIp()
    {
        using var limiter = RateLimitPolicy.Create(
            permitPerMinute: RateLimitPolicy.DefaultPermitPerMinute,
            waitlistPermitPerMinute: RateLimitPolicy.DefaultWaitlistPermitPerMinute);

        var caller = Context("/catalog/waitlist", "203.0.113.7");

        for (var i = 1; i <= RateLimitPolicy.DefaultWaitlistPermitPerMinute; i++)
        {
            using var lease = limiter.AttemptAcquire(caller);
            Assert.True(lease.IsAcquired, $"request {i} should be inside the 5/min budget");
        }

        using (var sixth = limiter.AttemptAcquire(caller))
        {
            Assert.False(sixth.IsAcquired);
        }

        // A different address is a different partition — one abuser does not lock out everyone.
        using var otherCaller = limiter.AttemptAcquire(Context("/catalog/waitlist", "198.51.100.4"));
        Assert.True(otherCaller.IsAcquired);
    }

    [Fact]
    public void Waitlist_BudgetIsSeparateFromOrdinaryBrowsing()
    {
        // The "waitlist:" partition prefix in both directions: spending the waitlist budget
        // must not throttle the same person's browsing, and browsing must not consume the
        // waitlist allowance.
        using var limiter = RateLimitPolicy.Create(120, 5);
        const string ip = "203.0.113.7";

        for (var i = 0; i < 5; i++)
        {
            using var lease = limiter.AttemptAcquire(Context("/catalog/waitlist", ip));
            Assert.True(lease.IsAcquired);
        }
        using (var exhausted = limiter.AttemptAcquire(Context("/catalog/waitlist", ip)))
        {
            Assert.False(exhausted.IsAcquired);
        }

        using var browse = limiter.AttemptAcquire(Context("/catalog", ip));
        Assert.True(browse.IsAcquired);
    }

    [Fact]
    public void Webhooks_RemainExemptFromThrottling()
    {
        // Providers retry on non-2xx. A 429'd webhook drops a fulfilment for someone who has
        // already been charged, so the money rail is never throttled — including from the same
        // address that just exhausted every other budget.
        using var limiter = RateLimitPolicy.Create(120, 5);

        for (var i = 0; i < 500; i++)
        {
            using var lease = limiter.AttemptAcquire(Context("/webhooks/stripe", "203.0.113.7"));
            Assert.True(lease.IsAcquired, $"webhook delivery {i} must never be throttled");
        }
    }

    private static DefaultHttpContext Context(string path, string ip)
    {
        var context = new DefaultHttpContext();
        context.Request.Path = path;
        context.Connection.RemoteIpAddress = IPAddress.Parse(ip);
        return context;
    }
}
