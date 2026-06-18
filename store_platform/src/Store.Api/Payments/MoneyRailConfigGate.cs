namespace Store.Api.Payments;

public sealed class MoneyRailConfigGate(IConfiguration config, ILogger<MoneyRailConfigGate> logger) : IHostedService
{
    // Required config keys per provider. The active provider must have every listed key
    // present or the app refuses to start (fail-closed): a money rail missing its webhook
    // secret accepts unsigned webhooks, and one missing its API key boots fine but fails
    // opaquely at the first checkout — both are caught here instead.
    private static readonly Dictionary<string, string[]> RequiredKeys =
        new(StringComparer.Ordinal)
        {
            ["paddle"] = ["Paddle:WebhookSecret"],
            ["stripe"] = ["Stripe:WebhookSecret", "Stripe:ApiKey"],
        };

    public Task StartAsync(CancellationToken cancellationToken)
    {
        var activeProvider = config["payments:active_provider"] ?? "paddle";

        if (!RequiredKeys.TryGetValue(activeProvider, out var requiredKeys))
        {
            var msg = $"CRITICAL: '{activeProvider}' is set as the active payment provider but is not a recognised provider. App refusing to start.";
            logger.LogCritical("{Message}", msg);
            throw new InvalidOperationException(msg);
        }

        var missingKey = Array.Find(requiredKeys, key => string.IsNullOrEmpty(config[key]));
        if (missingKey is not null)
        {
            var msg = $"CRITICAL: '{activeProvider}' is the active payment provider but '{missingKey}' is missing. App refusing to start.";
            logger.LogCritical("{Message}", msg);
            throw new InvalidOperationException(msg);
        }

        return Task.CompletedTask;
    }

    public Task StopAsync(CancellationToken cancellationToken) => Task.CompletedTask;
}
