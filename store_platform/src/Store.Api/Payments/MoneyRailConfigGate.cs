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

    // P1-4 — the dev convenience value for the engine publish-authorization key, committed in
    // appsettings.Development.json. Same trust class as the internal key: never the effective
    // entitlements key outside Development.
    private const string DevPlaceholderEntitlementsKey = "dev-entitlements-key-change-in-production";

    // P1-4 — the dev convenience value for the Paddle webhook signing secret, committed in
    // appsettings.Development.json. Same trust class as the keys above: a webhook secret left
    // at this committed value outside Development means anyone who can read this repo knows the
    // HMAC secret and can forge a valid Paddle webhook (a free entitlement). Fail closed.
    private const string DevPlaceholderPaddleWebhookSecret = "dev-paddle-webhook-secret";

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
        GuardEntitlementsApiKey();

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

        GuardWebhookSecretPlaceholder(activeProvider);

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

    // P1-4 — outside Development, the engine publish-authorization key (checked by the
    // POST /entitlements gate) must be a real secret: not missing, and not the committed dev
    // placeholder. In Development we allow the placeholder so local publishes work.
    private void GuardEntitlementsApiKey()
    {
        if (environment.IsDevelopment())
        {
            return;
        }

        var key = config["Store:EntitlementsApiKey"]
            ?? Environment.GetEnvironmentVariable("PROSPECTOR_ENTITLEMENTS_API_KEY");

        if (string.IsNullOrEmpty(key)
            || string.Equals(key, DevPlaceholderEntitlementsKey, StringComparison.Ordinal))
        {
            var msg = $"CRITICAL: Store:EntitlementsApiKey is missing or set to the dev placeholder "
                + $"in the '{environment.EnvironmentName}' environment. App refusing to start.";
            logger.LogCritical("{Message}", msg);
            throw new InvalidOperationException(msg);
        }
    }

    // P1-4 — presence of the webhook secret is checked above; this additionally refuses the
    // committed dev placeholder outside Development. Unlike a missing key (caught generically),
    // a placeholder value is a *present* secret that is publicly known, so signature
    // verification would pass for a forged webhook. Fail closed.
    private void GuardWebhookSecretPlaceholder(string activeProvider)
    {
        if (environment.IsDevelopment())
        {
            return;
        }

        if (string.Equals(activeProvider, "paddle", StringComparison.Ordinal)
            && string.Equals(config["Paddle:WebhookSecret"], DevPlaceholderPaddleWebhookSecret, StringComparison.Ordinal))
        {
            var msg = $"CRITICAL: Paddle:WebhookSecret is set to the dev placeholder in the "
                + $"'{environment.EnvironmentName}' environment. App refusing to start.";
            logger.LogCritical("{Message}", msg);
            throw new InvalidOperationException(msg);
        }
    }

    public Task StopAsync(CancellationToken cancellationToken) => Task.CompletedTask;
}
