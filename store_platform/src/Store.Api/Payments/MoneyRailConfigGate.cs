using Microsoft.Extensions.Hosting;

namespace Store.Api.Payments;

public sealed class MoneyRailConfigGate(
    IConfiguration config,
    IHostEnvironment environment,
    ILogger<MoneyRailConfigGate> logger) : IHostedService
{
    // P1-4 — the dev convenience value committed in appsettings.Development.json. It must
    // never be the effective internal key outside Development; the startup guard fails
    // closed if it (or an empty key) is present in any other environment.
    private const string DevPlaceholderInternalKey = "dev-test-key-change-in-production";

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
        GuardInternalApiKey();

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

    // P1-4 — outside Development, the engine→store publish key must be a real secret: not
    // missing, and not the committed dev placeholder. An unauthenticated/known-key publish
    // endpoint lets anyone push to the catalogue. In Development we allow the placeholder
    // so local runs work without secret setup.
    private void GuardInternalApiKey()
    {
        if (environment.IsDevelopment())
        {
            return;
        }

        var key = config["Store:InternalApiKey"]
            ?? Environment.GetEnvironmentVariable("STORE_INTERNAL_API_KEY");

        if (string.IsNullOrEmpty(key)
            || string.Equals(key, DevPlaceholderInternalKey, StringComparison.Ordinal))
        {
            var msg = $"CRITICAL: Store:InternalApiKey is missing or set to the dev placeholder "
                + $"in the '{environment.EnvironmentName}' environment. App refusing to start.";
            logger.LogCritical("{Message}", msg);
            throw new InvalidOperationException(msg);
        }
    }

    public Task StopAsync(CancellationToken cancellationToken) => Task.CompletedTask;
}
