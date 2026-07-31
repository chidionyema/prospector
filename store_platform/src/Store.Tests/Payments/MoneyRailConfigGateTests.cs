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
            ["Stripe:ApiKey"] = "sk_test_fake",
            // AC-5 — Production now refuses to start without a post-payment redirect target,
            // so the shared fixture supplies one. Tests that exercise that guard blank it out.
            ["Store:AllowedOrigin"] = "https://storefront.example",
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
        // Production happy path: BOTH the internal key and the entitlements publish key must be
        // real secrets (GuardInternalApiKey + GuardEntitlementsApiKey both run in Production).
        var config = StripeConfig(
            ("Store:InternalApiKey", "a-real-rotated-secret"),
            ("Store:EntitlementsApiKey", "a-real-rotated-entitlements-secret"));
        var gate = NewGate(config, "Production");
        var exception = await Record.ExceptionAsync(() => gate.StartAsync(CancellationToken.None));
        Assert.Null(exception);
    }

    [Fact]
    public Task StartAsync_ProductionWithMissingEntitlementsKey_Throws()
    {
        // Internal key real but entitlements publish key absent: the publish endpoint would be
        // unprotected. The gate must fail closed at startup.
        var config = StripeConfig(("Store:InternalApiKey", "a-real-rotated-secret"));
        var gate = NewGate(config, "Production");
        return Assert.ThrowsAsync<InvalidOperationException>(() => gate.StartAsync(CancellationToken.None));
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
                ["Stripe:ApiKey"] = "sk_test_fake",
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
                ["Stripe:ApiKey"] = "sk_test_fake",
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

    // --- P1-4: a webhook secret left at its committed dev placeholder is a *present* but
    // publicly-known HMAC key, so a forged webhook would verify. Fail closed outside Dev. ---

    [Fact]
    public Task StartAsync_ProductionWithPaddlePlaceholderSecret_Throws()
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>(StringComparer.Ordinal)
            {
                ["payments:active_provider"] = "paddle",
                // Real publish keys so we reach the provider-secret placeholder check.
                ["Store:InternalApiKey"] = "a-real-rotated-secret",
                ["Store:EntitlementsApiKey"] = "a-real-rotated-entitlements-secret",
                ["Paddle:WebhookSecret"] = "dev-paddle-webhook-secret", // committed dev placeholder
            })
            .Build();
        var gate = NewGate(config, "Production");
        return Assert.ThrowsAsync<InvalidOperationException>(() => gate.StartAsync(CancellationToken.None));
    }

    [Fact]
    public async Task StartAsync_DevelopmentWithPaddlePlaceholderSecret_Succeeds()
    {
        // The committed placeholder is the intended local value; the guard is Dev-skipped.
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>(StringComparer.Ordinal)
            {
                ["payments:active_provider"] = "paddle",
                ["Paddle:WebhookSecret"] = "dev-paddle-webhook-secret",
            })
            .Build();
        var gate = NewGate(config, "Development");
        var exception = await Record.ExceptionAsync(() => gate.StartAsync(CancellationToken.None));
        Assert.Null(exception);
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

    // --- AC-5: Stripe:ApiKey SHAPE. Presence is checked above, but a present-and-malformed
    // key boots a healthy-looking app and 500s the first buyer at checkout, because the key is
    // otherwise only touched lazily in StripeProvider.EnsureStripeConfigured. ---

    [Theory]
    [InlineData("not-a-key")]
    [InlineData("sk_test")]      // real Stripe keys always carry the trailing underscore
    [InlineData("sk_liv_abc")]   // near-miss typo
    [InlineData("pk_live_abc")]  // publishable key pasted where the secret key belongs
    [InlineData("whsec_abc")]    // webhook secret pasted into the API key slot
    public Task StartAsync_MalformedStripeApiKey_Throws(string apiKey)
    {
        var config = StripeConfig(("Stripe:ApiKey", apiKey));
        var gate = NewGate(config);
        return Assert.ThrowsAsync<InvalidOperationException>(() => gate.StartAsync(CancellationToken.None));
    }

    [Theory]
    [InlineData("sk_live_abc")]
    [InlineData("sk_test_abc")]
    [InlineData("rk_live_abc")] // restricted keys are legitimate server-side keys
    [InlineData("rk_test_abc")]
    public async Task StartAsync_WellFormedStripeApiKey_Succeeds(string apiKey)
    {
        var config = StripeConfig(("Stripe:ApiKey", apiKey));
        var gate = NewGate(config);
        var exception = await Record.ExceptionAsync(() => gate.StartAsync(CancellationToken.None));
        Assert.Null(exception);
    }

    [Fact]
    public async Task StartAsync_TestModeKeyInProduction_DoesNotThrow()
    {
        // Deliberate: staging runs ASPNETCORE_ENVIRONMENT=Production for parity and differs
        // only in its secrets (deploy/fly/api.staging.fly.toml:17-18). Throwing here would make
        // staging unbootable, so a test-mode key is a loud CRITICAL log, not a startup failure.
        var config = StripeConfig(
            ("Stripe:ApiKey", "sk_test_abc"),
            ("Store:InternalApiKey", "a-real-rotated-secret"),
            ("Store:EntitlementsApiKey", "a-real-rotated-entitlements-secret"));
        var gate = NewGate(config, "Production");

        var exception = await Record.ExceptionAsync(() => gate.StartAsync(CancellationToken.None));

        Assert.Null(exception);
    }

    // --- AC-5: the post-payment redirect target. Previously a CRITICAL log the app ignored,
    // which booted "healthy" and sent every paying buyer to a 404 on the API host. ---

    [Fact]
    public Task StartAsync_ProductionWithNoStorefrontUrl_Throws()
    {
        var config = StripeConfig(
            ("Store:InternalApiKey", "a-real-rotated-secret"),
            ("Store:EntitlementsApiKey", "a-real-rotated-entitlements-secret"),
            ("Store:AllowedOrigin", ""),
            ("Store:StorefrontUrl", ""));
        var gate = NewGate(config, "Production");

        return Assert.ThrowsAsync<InvalidOperationException>(() => gate.StartAsync(CancellationToken.None));
    }

    [Fact]
    public async Task StartAsync_ProductionWithStorefrontUrlOnly_Succeeds()
    {
        // StorefrontUrl alone is sufficient — AllowedOrigin is only the fallback.
        var config = StripeConfig(
            ("Store:InternalApiKey", "a-real-rotated-secret"),
            ("Store:EntitlementsApiKey", "a-real-rotated-entitlements-secret"),
            ("Store:AllowedOrigin", ""),
            ("Store:StorefrontUrl", "https://storefront.example"));
        var gate = NewGate(config, "Production");

        var exception = await Record.ExceptionAsync(() => gate.StartAsync(CancellationToken.None));

        Assert.Null(exception);
    }

    [Fact]
    public async Task StartAsync_DevelopmentWithNoStorefrontUrl_Succeeds()
    {
        var config = StripeConfig(("Store:AllowedOrigin", ""), ("Store:StorefrontUrl", ""));
        var gate = NewGate(config);

        var exception = await Record.ExceptionAsync(() => gate.StartAsync(CancellationToken.None));

        Assert.Null(exception);
    }

    // --- AC-5: R2 delivery config is all-or-nothing. A PARTIAL config leaves already-listed
    // packs sellable while every download 503s — buyers pay for undeliverable content. ---

    private static (string, string)[] ProductionKeys() =>
    [
        ("Store:InternalApiKey", "a-real-rotated-secret"),
        ("Store:EntitlementsApiKey", "a-real-rotated-entitlements-secret"),
    ];

    [Theory]
    [InlineData("R2:AccessKeyId")]
    [InlineData("R2:SecretAccessKey")]
    [InlineData("R2:Bucket")]
    public Task StartAsync_ProductionWithPartialR2Config_Throws(string omittedKey)
    {
        var r2 = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["R2:AccountId"] = "acct",
            ["R2:AccessKeyId"] = "ak",
            ["R2:SecretAccessKey"] = "sk",
            ["R2:Bucket"] = "bucket",
        };
        r2[omittedKey] = "";

        var extra = new List<(string, string)>(ProductionKeys());
        extra.AddRange(r2.Select(kv => (kv.Key, kv.Value)));

        var gate = NewGate(StripeConfig([.. extra]), "Production");

        return Assert.ThrowsAsync<InvalidOperationException>(() => gate.StartAsync(CancellationToken.None));
    }

    [Fact]
    public async Task StartAsync_ProductionWithCompleteR2Config_Succeeds()
    {
        var extra = new List<(string, string)>(ProductionKeys())
        {
            ("R2:AccountId", "acct"),
            ("R2:AccessKeyId", "ak"),
            ("R2:SecretAccessKey", "sk"),
            ("R2:Bucket", "bucket"),
        };
        var gate = NewGate(StripeConfig([.. extra]), "Production");

        var exception = await Record.ExceptionAsync(() => gate.StartAsync(CancellationToken.None));

        Assert.Null(exception);
    }

    [Fact]
    public async Task StartAsync_ProductionWithNoR2ConfigAtAll_Succeeds()
    {
        // Nothing set is a legitimate state: packs register UNLISTED, so nothing can be sold
        // undeliverably. Only a PARTIAL config is unambiguously an operator error.
        var gate = NewGate(StripeConfig(ProductionKeys()), "Production");

        var exception = await Record.ExceptionAsync(() => gate.StartAsync(CancellationToken.None));

        Assert.Null(exception);
    }
}
