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

    /// <summary>The fake rail every request resolves; flip <see cref="FakePaymentProvider.CanBill"/> per test.</summary>
    public FakePaymentProvider Payments { get; } = new();

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseSetting("ConnectionStrings:DefaultConnection", $"Data Source={_dbPath}");
        builder.UseSetting("Store:InternalApiKey", InternalKey);

        builder.ConfigureServices(services =>
        {
            // Replace both keyed rails: a test must never reach the real Stripe, and a pack's
            // stored provider decides which key is resolved.
            services.AddKeyedSingleton<IPaymentProvider>("stripe", (_, _) => Payments);
            services.AddKeyedSingleton<IPaymentProvider>("paddle", (_, _) => Payments);
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
