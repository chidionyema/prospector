using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging.Abstractions;
using Store.Api.Payments;

namespace Store.Tests.Payments;

public sealed class MoneyRailConfigGateTests
{
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

        var gate = new MoneyRailConfigGate(config, NullLogger<MoneyRailConfigGate>.Instance);

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

        var gate = new MoneyRailConfigGate(config, NullLogger<MoneyRailConfigGate>.Instance);

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

        var gate = new MoneyRailConfigGate(config, NullLogger<MoneyRailConfigGate>.Instance);

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

        var gate = new MoneyRailConfigGate(config, NullLogger<MoneyRailConfigGate>.Instance);

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

        var gate = new MoneyRailConfigGate(config, NullLogger<MoneyRailConfigGate>.Instance);

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

        var gate = new MoneyRailConfigGate(config, NullLogger<MoneyRailConfigGate>.Instance);

        return Assert.ThrowsAsync<InvalidOperationException>(() => gate.StartAsync(CancellationToken.None));
    }
}
