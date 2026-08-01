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
        GuardStripeApiKeyShape(activeProvider);
        GuardStorefrontUrl();
        GuardEmailWebBaseUrl();
        GuardR2Config();
        ReportDeliveryConfig();

        return Task.CompletedTask;
    }

    // AC-5 — presence of Stripe:ApiKey is enforced by RequiredKeys above, but presence is not
    // enough: the key is otherwise first *used* lazily at the first checkout
    // (StripeProvider.EnsureStripeConfigured), so a malformed key boots a healthy-looking app
    // and then 500s the first buyer who tries to pay. Validate the shape at startup instead.
    //
    // Deliberately NOT fatal on a test-mode key in the Production environment: staging runs
    // ASPNETCORE_ENVIRONMENT=Production on purpose for parity and differs only in its secrets
    // (deploy/fly/api.staging.fly.toml:17-18), so throwing here would make staging unbootable.
    // A test key on the real store takes no real money, which is loud enough to find fast; a
    // malformed key is unambiguously broken, so that one throws.
    private void GuardStripeApiKeyShape(string activeProvider)
    {
        if (!string.Equals(activeProvider, "stripe", StringComparison.Ordinal))
        {
            return;
        }

        var apiKey = config["Stripe:ApiKey"] ?? string.Empty;

        // sk_ = standard secret key, rk_ = restricted key; both are valid server-side keys.
        var isLive = apiKey.StartsWith("sk_live_", StringComparison.Ordinal)
            || apiKey.StartsWith("rk_live_", StringComparison.Ordinal);
        var isTest = apiKey.StartsWith("sk_test_", StringComparison.Ordinal)
            || apiKey.StartsWith("rk_test_", StringComparison.Ordinal);

        if (!isLive && !isTest)
        {
            var msg = "CRITICAL: Stripe:ApiKey is not a recognised Stripe secret key "
                + "(expected sk_live_/sk_test_/rk_live_/rk_test_ prefix). A malformed key boots "
                + "fine and then fails the first buyer at checkout. App refusing to start.";
            logger.LogCritical("{Message}", msg);
            throw new InvalidOperationException(msg);
        }

        if (isTest && !environment.IsDevelopment())
        {
            logger.LogCritical(
                "MONEY-RAIL-TEST-MODE: Stripe:ApiKey is a TEST key in the '{Environment}' "
                + "environment. Checkout will complete but NO real money is taken. This is "
                + "expected on staging and is a live-store outage anywhere else.",
                environment.EnvironmentName);
        }
    }

    // AC-5 — the post-payment redirect target. This was previously only a CRITICAL log line,
    // which meant a misconfigured deploy booted "healthy" and sent every paying buyer to a 404
    // on the API host (Program.cs builds the return URL from these). Money having already
    // changed hands by that point is exactly what fail-closed exists to prevent, so refuse to
    // start instead of logging and carrying on.
    private void GuardStorefrontUrl()
    {
        if (environment.IsDevelopment())
        {
            return;
        }

        if (string.IsNullOrWhiteSpace(ResolveStorefrontUrl()))
        {
            var msg = "CRITICAL: neither Store:StorefrontUrl (STORE_STOREFRONT_URL) nor "
                + "Store:AllowedOrigin (STORE_ALLOWED_ORIGIN) is set, so every buyer would be "
                + "redirected to this API after paying and land on a 404. App refusing to start.";
            logger.LogCritical("{Message}", msg);
            throw new InvalidOperationException(msg);
        }
    }

    // Email:WebBaseUrl is the storefront base every ACCOUNT link is built from: the verification,
    // password-reset and resend emails (EmailOptions consumers) and the post-consent OAuth landing
    // (ExternalAuthEndpoints.SafeRedirect). Unset, it defaults to http://localhost:3000.
    //
    // This ran unset in production on 2026-08-01. Nothing looked wrong — the API was healthy, the
    // mail sent, only the link inside it pointed at the recipient's own machine. Because order
    // history is gated on EmailConfirmed, no account created in that window could ever reach its
    // orders. A silent default that only shows up in someone else's inbox is exactly the shape
    // GuardStorefrontUrl already refuses to boot on, so this refuses too.
    //
    // It is also rejected when it merely POINTS at localhost/127.0.0.1: the failure is not "empty",
    // it is "resolves on the buyer's machine instead of ours", and the default value is non-empty.
    private void GuardEmailWebBaseUrl()
    {
        if (environment.IsDevelopment())
        {
            return;
        }

        var configured = config["Email:WebBaseUrl"];

        if (string.IsNullOrWhiteSpace(configured) || IsLoopback(configured))
        {
            var msg = "CRITICAL: Email:WebBaseUrl (Email__WebBaseUrl) is missing or points at "
                + $"localhost in the '{environment.EnvironmentName}' environment (value: "
                + $"'{configured ?? "<unset>"}'). Every verification, password-reset and OAuth "
                + "landing link would be sent to the recipient's own machine, and order history "
                + "is gated on a confirmed email. Set it to the STOREFRONT base URL. App refusing "
                + "to start.";
            logger.LogCritical("{Message}", msg);
            throw new InvalidOperationException(msg);
        }
    }

    private static bool IsLoopback(string url) =>
        Uri.TryCreate(url, UriKind.Absolute, out var uri)
        && (string.Equals(uri.Host, "localhost", StringComparison.OrdinalIgnoreCase)
            || string.Equals(uri.Host, "127.0.0.1", StringComparison.Ordinal)
            || string.Equals(uri.Host, "[::1]", StringComparison.Ordinal));

    private string? ResolveStorefrontUrl() =>
        config["Store:StorefrontUrl"]
            ?? Environment.GetEnvironmentVariable("STORE_STOREFRONT_URL")
            ?? config["Store:AllowedOrigin"]
            ?? Environment.GetEnvironmentVariable("STORE_ALLOWED_ORIGIN");

    // AC-5 — R2 delivery config is all-or-nothing. R2StorageBridge already treats a PARTIAL
    // config as unconfigured so it never builds malformed presigned URLs, but "unconfigured"
    // downloads answer 503 — and if the catalogue was seeded while R2 worked, packs stay LISTED
    // and sellable while every download 503s. That is the paid-but-undeliverable case.
    //
    // Nothing set at all is left alone: that is a legitimate state (packs register UNLISTED, so
    // nothing can be sold undeliverably). A partial config is never intentional, so it throws.
    private void GuardR2Config()
    {
        if (environment.IsDevelopment() || !string.IsNullOrEmpty(config["Storage:ServiceUrl"]))
        {
            return;
        }

        var keys = new (string Name, string? Value)[]
        {
            ("R2_ACCOUNT_ID", Read("R2:AccountId", "R2_ACCOUNT_ID")),
            ("R2_ACCESS_KEY_ID", Read("R2:AccessKeyId", "R2_ACCESS_KEY_ID")),
            ("R2_SECRET_ACCESS_KEY", Read("R2:SecretAccessKey", "R2_SECRET_ACCESS_KEY")),
            ("R2_BUCKET", Read("R2:Bucket", "R2_BUCKET")),
        };

        var missing = Array.FindAll(keys, k => string.IsNullOrWhiteSpace(k.Value));
        if (missing.Length == 0 || missing.Length == keys.Length)
        {
            return;
        }

        var msg = "CRITICAL: R2 delivery config is PARTIAL — missing "
            + string.Join(", ", Array.ConvertAll(missing, k => k.Name))
            + ". Downloads would return 503 while already-listed packs stay sellable, so buyers "
            + "could pay for content that cannot be delivered. Set all four R2 keys or none. "
            + "App refusing to start.";
        logger.LogCritical("{Message}", msg);
        throw new InvalidOperationException(msg);
    }

    private string? Read(string key, string env) =>
        config[key] ?? Environment.GetEnvironmentVariable(env);

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

        // Mailjet authenticates with a key PAIR, so all three parts must be present — a key
        // without its secret is as dead as no key at all, and reporting only on the key would
        // hide exactly that half-configured case.
        var mailKey = config["Mailjet:ApiKey"]
            ?? Environment.GetEnvironmentVariable("MAILJET_API_KEY");
        var mailSecret = config["Mailjet:ApiSecret"]
            ?? Environment.GetEnvironmentVariable("MAILJET_API_SECRET");
        var mailFrom = config["Mailjet:FromEmail"]
            ?? Environment.GetEnvironmentVariable("MAILJET_FROM_EMAIL");

        if (string.IsNullOrWhiteSpace(mailKey)
            || string.IsNullOrWhiteSpace(mailSecret)
            || string.IsNullOrWhiteSpace(mailFrom))
        {
            logger.LogCritical(
                "DELIVERY-DEGRADED: Mailjet is not fully configured (ApiKey set: {HasKey}, "
                + "ApiSecret set: {HasSecret}, FromEmail set: {HasFrom}). Buyers will receive NO "
                + "fulfilment email; delivery depends entirely on the success page. Set "
                + "MAILJET_API_KEY, MAILJET_API_SECRET and MAILJET_FROM_EMAIL to restore "
                + "email delivery.",
                !string.IsNullOrWhiteSpace(mailKey),
                !string.IsNullOrWhiteSpace(mailSecret),
                !string.IsNullOrWhiteSpace(mailFrom));
        }

        // The post-payment redirect target used to be reported here as DELIVERY-DEGRADED and
        // then ignored. It is now a fatal startup guard (GuardStorefrontUrl) — landing a paying
        // buyer on a 404 is not a degraded mode, it is a lost sale with the money already taken.
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
