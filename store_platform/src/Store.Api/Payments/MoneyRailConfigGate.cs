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
        ReportDeliveryConfig();

        return Task.CompletedTask;
    }

    // Delivery config is reported loudly at boot but does NOT refuse startup. A missing mail
    // token is degraded, not fatal: the storefront success page resolves the buyer's download
    // directly from the checkout session, so a purchase is still deliverable without email.
    // The reason this is here at all is that it previously failed *silently* — no token, no
    // email, no log, and a fulfilment path that looked healthy while buyers got nothing.
    private void ReportDeliveryConfig()
    {
        if (environment.IsDevelopment())
        {
            return;
        }

        var mailToken = config["Postmark:ServerToken"]
            ?? Environment.GetEnvironmentVariable("POSTMARK_SERVER_TOKEN");
        var mailFrom = config["Postmark:FromEmail"]
            ?? Environment.GetEnvironmentVariable("POSTMARK_FROM_EMAIL");

        if (string.IsNullOrWhiteSpace(mailToken) || string.IsNullOrWhiteSpace(mailFrom))
        {
            logger.LogCritical(
                "DELIVERY-DEGRADED: Postmark is not fully configured (ServerToken set: {HasToken}, "
                + "FromEmail set: {HasFrom}). Buyers will receive NO fulfilment email; delivery "
                + "depends entirely on the success page. Set POSTMARK_SERVER_TOKEN and "
                + "POSTMARK_FROM_EMAIL to restore email delivery.",
                !string.IsNullOrWhiteSpace(mailToken), !string.IsNullOrWhiteSpace(mailFrom));
        }

        // The post-payment redirect must reach the storefront. With neither of these set it
        // falls back to this API's own host, where /orders/success does not exist — which is
        // exactly the 404-after-paying failure this check exists to make visible.
        var storefront = config["Store:StorefrontUrl"]
            ?? Environment.GetEnvironmentVariable("STORE_STOREFRONT_URL")
            ?? config["Store:AllowedOrigin"]
            ?? Environment.GetEnvironmentVariable("STORE_ALLOWED_ORIGIN");

        if (string.IsNullOrWhiteSpace(storefront))
        {
            logger.LogCritical(
                "DELIVERY-DEGRADED: neither Store:StorefrontUrl nor Store:AllowedOrigin is set, so the "
                + "post-payment redirect will target this API instead of the storefront and every "
                + "paying buyer will land on a 404. Set STORE_STOREFRONT_URL to the storefront origin.");
        }
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
