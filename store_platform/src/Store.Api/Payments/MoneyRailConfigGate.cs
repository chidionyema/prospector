namespace Store.Api.Payments;

public sealed class MoneyRailConfigGate(IConfiguration config, ILogger<MoneyRailConfigGate> logger) : IHostedService
{
    // Required config key per provider. The active provider must have its secret present
    // or the app refuses to start (fail-closed): a money rail with no verification secret
    // would accept unsigned webhooks or silently drop signed ones.
    private static readonly Dictionary<string, string> RequiredSecretKey =
        new(StringComparer.Ordinal)
        {
            ["paddle"] = "Paddle:WebhookSecret",
            ["stripe"] = "Stripe:WebhookSecret",
        };

    public Task StartAsync(CancellationToken cancellationToken)
    {
        var activeProvider = config["payments:active_provider"] ?? "paddle";

        if (!RequiredSecretKey.TryGetValue(activeProvider, out var secretKey))
        {
            var msg = $"CRITICAL: '{activeProvider}' is set as the active payment provider but is not a recognised provider. App refusing to start.";
            logger.LogCritical("{Message}", msg);
            throw new InvalidOperationException(msg);
        }

        if (string.IsNullOrEmpty(config[secretKey]))
        {
            var msg = $"CRITICAL: '{activeProvider}' is the active payment provider but '{secretKey}' is missing. App refusing to start.";
            logger.LogCritical("{Message}", msg);
            throw new InvalidOperationException(msg);
        }

        return Task.CompletedTask;
    }

    public Task StopAsync(CancellationToken cancellationToken) => Task.CompletedTask;
}
