using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.FileProviders;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Primitives;
using Store.Api.Payments;

namespace Store.Tests.Payments;

public sealed class MoneyRailConfigGateTests
{
    private const string DevKey = "dev-test-key-change-in-production";

    // Existing provider-secret tests run under Development so the internal-key guard
    // (P1-4) is skipped and they exercise only the provider-secret checks.
    private static MoneyRailConfigGate NewGate(IConfiguration config, string env = "Development") =>
        new(config, new FakeHostEnvironment(env), NullLogger<MoneyRailConfigGate>.Instance);

    private static IConfiguration StripeConfig(params (string Key, string Value)[] extra)
    {
        var dict = new Dictionary<string, string?>(StringComparer.Ordinal)
        {
            ["payments:active_provider"] = "stripe",
            ["Stripe:WebhookSecret"] = "whsec_test",
            ["Stripe:ApiKey"] = "sk_test",
        };
        foreach (var (k, v) in extra)
        {
            dict[k] = v;
        }
        return new ConfigurationBuilder().AddInMemoryCollection(dict).Build();
    }

    // --- P1-4: the engine→store internal API key guard ---

    [Fact]
    public Task StartAsync_ProductionWithDevPlaceholderKey_Throws()
    {
        var config = StripeConfig(("Store:InternalApiKey", DevKey));
        var gate = NewGate(config, "Production");
        return Assert.ThrowsAsync<InvalidOperationException>(() => gate.StartAsync(CancellationToken.None));
    }

    [Fact]
    public Task StartAsync_ProductionWithMissingInternalKey_Throws()
    {
        var config = StripeConfig(); // no Store:InternalApiKey
        var gate = NewGate(config, "Production");
        return Assert.ThrowsAsync<InvalidOperationException>(() => gate.StartAsync(CancellationToken.None));
    }

    [Fact]
    public async Task StartAsync_ProductionWithRealInternalKey_Succeeds()
    {
        var config = StripeConfig(("Store:InternalApiKey", "a-real-rotated-secret"));
        var gate = NewGate(config, "Production");
        var exception = await Record.ExceptionAsync(() => gate.StartAsync(CancellationToken.None));
        Assert.Null(exception);
    }

    [Fact]
    public async Task StartAsync_DevelopmentWithDevPlaceholderKey_Succeeds()
    {
        var config = StripeConfig(("Store:InternalApiKey", DevKey));
        var gate = NewGate(config, "Development");
        var exception = await Record.ExceptionAsync(() => gate.StartAsync(CancellationToken.None));
        Assert.Null(exception);
    }

    private sealed class FakeHostEnvironment(string environmentName) : IHostEnvironment
    {
        public string EnvironmentName { get; set; } = environmentName;
        public string ApplicationName { get; set; } = "Store.Tests";
        public string ContentRootPath { get; set; } = AppContext.BaseDirectory;
        public IFileProvider ContentRootFileProvider { get; set; } =
            new NullFileProvider();
    }

    [Fact]
    public Task StartAsync_PaddleActiveButSecretMissing_Throws()
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>(StringComparer.Ordinal)
            {
                ["payments:active_provider"] = "paddle",
                ["Paddle:WebhookSecret"] = "" // missing
            })
            .Build();

        var gate = NewGate(config);

        return Assert.ThrowsAsync<InvalidOperationException>(() => gate.StartAsync(CancellationToken.None));
    }

    [Fact]
    public async Task StartAsync_PaddleActiveAndSecretPresent_Succeeds()
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>(StringComparer.Ordinal)
            {
                ["payments:active_provider"] = "paddle",
                ["Paddle:WebhookSecret"] = "shhh"
            })
            .Build();

        var gate = NewGate(config);

        var exception = await Record.ExceptionAsync(() => gate.StartAsync(CancellationToken.None));
        Assert.Null(exception);
    }

    [Fact]
    public async Task StartAsync_OtherProviderActive_DoesNotCheckPaddleSecret()
    {
        // Stripe active + its own secret present: the gate must validate Stripe's secret,
        // not Paddle's. Paddle's missing secret is irrelevant when paddle isn't active.
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>(StringComparer.Ordinal)
            {
                ["payments:active_provider"] = "stripe",
                ["Stripe:WebhookSecret"] = "whsec_test",
                ["Stripe:ApiKey"] = "sk_test",
                ["Paddle:WebhookSecret"] = "" // missing but doesn't matter
            })
            .Build();

        var gate = NewGate(config);

        var exception = await Record.ExceptionAsync(() => gate.StartAsync(CancellationToken.None));
        Assert.Null(exception);
    }

    [Fact]
    public Task StartAsync_StripeActiveButSecretMissing_Throws()
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>(StringComparer.Ordinal)
            {
                ["payments:active_provider"] = "stripe",
                ["Stripe:ApiKey"] = "sk_test",
                ["Stripe:WebhookSecret"] = "" // missing
            })
            .Build();

        var gate = NewGate(config);

        return Assert.ThrowsAsync<InvalidOperationException>(() => gate.StartAsync(CancellationToken.None));
    }

    [Fact]
    public Task StartAsync_StripeActiveButApiKeyMissing_Throws()
    {
        // Webhook secret present but no API key: the app would boot and only fail at the
        // first checkout with an opaque Stripe SDK error. The gate must catch it at startup.
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>(StringComparer.Ordinal)
            {
                ["payments:active_provider"] = "stripe",
                ["Stripe:WebhookSecret"] = "whsec_test",
                ["Stripe:ApiKey"] = "" // missing
            })
            .Build();

        var gate = NewGate(config);

        return Assert.ThrowsAsync<InvalidOperationException>(() => gate.StartAsync(CancellationToken.None));
    }

    [Fact]
    public Task StartAsync_UnknownProviderActive_Throws()
    {
        // A misconfigured/unrecognised active provider must fail closed — never run the
        // money rail with no verification path.
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>(StringComparer.Ordinal)
            {
                ["payments:active_provider"] = "bogus",
            })
            .Build();

        var gate = NewGate(config);

        return Assert.ThrowsAsync<InvalidOperationException>(() => gate.StartAsync(CancellationToken.None));
    }
}
