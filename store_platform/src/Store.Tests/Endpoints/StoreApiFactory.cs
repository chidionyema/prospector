using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Store.Api.Payments;
using Store.Api.Services;

namespace Store.Tests.Endpoints;

/// <summary>
/// Boots the real API in-process, against a throwaway SQLite file, with the payment rail faked.
/// </summary>
/// <remarks>
/// Exists because the money-rail guards live in endpoint wiring, and until now nothing tested
/// wiring: every rule was covered as a pure function it happens to call. The list-only-if-billable
/// guard could have been deleted from Program.cs with all 160 tests still green. Rules tested
/// apart from their wiring are exactly how a fence ends up present in the source and absent in
/// production.
/// <para>
/// The app migrates on startup, so a fresh file provisions its own schema; each factory gets its
/// own so tests cannot leak state into one another.
/// </para>
/// </remarks>
public sealed class StoreApiFactory : WebApplicationFactory<Program>
{
    public const string InternalKey = "test-internal-key";

    private readonly string _dbPath = Path.Combine(
        Path.GetTempPath(), $"store-test-{Guid.NewGuid():N}.db");

    /// <summary>A throwaway RSA key, generated once per test run. 2048-bit because that is what
    /// production uses — a smaller key would test a different code path in RS256 signing.</summary>
    private static readonly string TestSigningKeyPem = CreateTestSigningKeyPem();

    private static string CreateTestSigningKeyPem()
    {
        using var rsa = System.Security.Cryptography.RSA.Create(2048);
        return rsa.ExportPkcs8PrivateKeyPem();
    }

    /// <summary>The fake rail every request resolves; flip <see cref="FakePaymentProvider.CanBill"/> per test.</summary>
    public FakePaymentProvider Payments { get; } = new();

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseSetting("ConnectionStrings:DefaultConnection", $"Data Source={_dbPath}");
        builder.UseSetting("Store:InternalApiKey", InternalKey);

        // Auth refuses to start without a signing key, deliberately: falling back to a generated
        // one would boot a misconfigured production API that mints tokens no other machine — and
        // no restart of the same machine — can validate. So the test host supplies its own. It is
        // generated per factory rather than checked in, so a key in the repo can never become a
        // key in production.
        builder.UseSetting("Jwt:SigningKeyPem", TestSigningKeyPem);
        builder.UseSetting("Jwt:Issuer", "https://store.test");
        builder.UseSetting("Jwt:Audience", "store-test");
        builder.UseSetting("Email:WebBaseUrl", "http://localhost:3000");

        // MoneyRailConfigGate refuses to start when the active provider is missing a required
        // key, and since Paddle was removed the active provider defaults to stripe. Same reason
        // as the signing key above: the test host supplies its own rather than the repo carrying
        // a committed secret. These values never reach Stripe — ConfigureServices below replaces
        // the "stripe" rail with FakePaymentProvider — but they must pass the shape guard, so the
        // key keeps the sk_test_ prefix a real key would have.
        builder.UseSetting("Stripe:WebhookSecret", "whsec_storeapifactory_not_a_real_secret");
        builder.UseSetting("Stripe:ApiKey", "sk_test_storeapifactory_not_a_real_key");

        builder.ConfigureServices(services =>
        {
            // Replace the keyed rail: a test must never reach the real Stripe.
            services.AddKeyedSingleton<IPaymentProvider>("stripe", (_, _) => Payments);
        });
    }

    protected override void Dispose(bool disposing)
    {
        base.Dispose(disposing);
        if (disposing)
        {
            File.Delete(_dbPath);
        }
    }
}
