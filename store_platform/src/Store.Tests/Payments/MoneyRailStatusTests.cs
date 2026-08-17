using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.FileProviders;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Primitives;
using Store.Api.Payments;

namespace Store.Tests.Payments;

/// <summary>
/// PAY-1. The startup gate already decided live-vs-test; it just never told anyone who could
/// act on it. These tests pin that the decision reaches <see cref="MoneyRailStatus"/>, which is
/// what /healthz/money-rail serves and what the deploy workflow fails on.
///
/// The case that matters is a TEST key in Production. Nothing else in the app notices it: the
/// machines boot, /catalog answers 200, checkout completes, and the buyer pays nothing.
/// </summary>
public sealed class MoneyRailStatusTests
{
    private static IConfiguration Config(string provider, string? apiKey)
    {
        var dict = new Dictionary<string, string?>(StringComparer.Ordinal)
        {
            ["payments:active_provider"] = provider,
            ["Stripe:WebhookSecret"] = "whsec_test",
            ["Stripe:ApiKey"] = apiKey,
            ["Paddle:WebhookSecret"] = "pdl_not_the_dev_placeholder",
            ["Store:AllowedOrigin"] = "https://storefront.example",
            ["Email:WebBaseUrl"] = "https://storefront.example",
            // Production runs the whole gate, not just the Stripe shape check. Without these the
            // internal-key and entitlements-key guards throw first and the test never reaches the
            // thing it is measuring. They are fixture values, not real keys.
            ["Store:InternalApiKey"] = "test-fixture-internal-key",
            ["Store:EntitlementsApiKey"] = "test-fixture-entitlements-key",
            ["Storage:ServiceUrl"] = "https://r2.example",
        };
        return new ConfigurationBuilder().AddInMemoryCollection(dict).Build();
    }

    private static async Task<MoneyRailStatus> RunGateAsync(
        string provider, string? apiKey, string env)
    {
        var status = new MoneyRailStatus();
        var gate = new MoneyRailConfigGate(
            Config(provider, apiKey),
            new FakeEnvironment(env),
            NullLogger<MoneyRailConfigGate>.Instance,
            status);
        await gate.StartAsync(CancellationToken.None);
        return status;
    }

    [Fact]
    public async Task LiveKey_RecordsLiveMode()
    {
        var status = await RunGateAsync("stripe", "sk_live_fake", "Development");

        Assert.Equal("stripe", status.Provider);
        Assert.Equal("live", status.Mode);
        Assert.NotNull(status.DecidedAtUtc);
    }

    [Fact]
    public async Task RestrictedLiveKey_AlsoCountsAsLive()
    {
        // rk_live_ is a restricted key and takes real money exactly like sk_live_. Reading only
        // the sk_ prefix would report a live rail as test and fail every deploy.
        var status = await RunGateAsync("stripe", "rk_live_fake", "Development");

        Assert.Equal("live", status.Mode);
    }

    [Fact]
    public async Task TestKeyInProduction_RecordsTestMode()
    {
        // THE case this exists for. The gate deliberately does not throw here, because staging
        // runs ASPNETCORE_ENVIRONMENT=Production on purpose. So the fact has to be readable.
        var status = await RunGateAsync("stripe", "sk_test_fake", "Production");

        Assert.Equal("test", status.Mode);
        Assert.Equal("Production", status.Environment);
    }

    [Fact]
    public async Task NonStripeProvider_RecordsNotApplicable()
    {
        var status = await RunGateAsync("paddle", null, "Development");

        Assert.Equal("paddle", status.Provider);
        Assert.Equal("not-applicable", status.Mode);
        Assert.NotNull(status.DecidedAtUtc);
    }

    [Fact]
    public void BeforeTheGateRuns_NothingIsClaimed()
    {
        // An app serving requests with no decision recorded did not run its money guard. That is
        // a different fault from a test key, and the deploy probe has to be able to tell them
        // apart — hence null rather than a default of "live" or "test".
        var status = new MoneyRailStatus();

        Assert.Null(status.DecidedAtUtc);
        Assert.Equal("unknown", status.Mode);
    }

    private sealed class FakeEnvironment(string environmentName) : IHostEnvironment
    {
        public string EnvironmentName { get; set; } = environmentName;
        public string ApplicationName { get; set; } = "Store.Tests";
        public string ContentRootPath { get; set; } = AppContext.BaseDirectory;
        public IFileProvider ContentRootFileProvider { get; set; } =
            new NullFileProvider();
    }
}
