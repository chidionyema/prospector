using Microsoft.EntityFrameworkCore;
using Store.Api.Common;
using Store.Api.Contracts;
using Store.Api.Payments;
using Store.Api.Services;
using Store.Catalog.Domain;
using Store.Catalog.Persistence;

namespace Store.Api.Endpoints;

/// <summary>
/// Checkout entry points. Both routes converge on one implementation: a basket of one is not a
/// special case, it is a basket. Keeping a separate single-pack path is how the cheap path and
/// the guarded path drift apart.
/// </summary>
public static class CheckoutEndpoints
{
    public static void MapCheckoutEndpoints(this IEndpointRouteBuilder app)
    {
        // --- CHECKOUT ENDPOINT (P4/P7 — provider-agnostic, hot-reloaded) ---
        // The provider for NEW checkouts is determined by the runtime config
        // `payments:active_provider` (P7 — seamless switch, no redeploy). For
        // packs published before the switch, the pack's stored PaymentProvider is
        // honoured as a fallback so the buyer's checkout always succeeds.
        app.MapPost("/packs/{id}/checkout", async (
            string id,
            StoreDbContext db,
            IServiceProvider sp,
            IConfiguration config,
            HttpRequest request) =>
        {
            var body = await ReadBodyAsync<CheckoutRequest>(request).ConfigureAwait(false);
            return await CreateCheckoutAsync([id], body?.Email, body?.Embedded ?? false, db, sp, config, request).ConfigureAwait(false);
        })
        .WithName("CreateCheckout")
        .WithOpenApi();

        // Basket checkout: several packs, one payment. The buyer who wants three blueprints
        // should enter their card once, not run three hosted checkouts and collect three
        // statement lines.
        app.MapPost("/checkout", async (
            StoreDbContext db,
            IServiceProvider sp,
            IConfiguration config,
            HttpRequest request) =>
        {
            var body = await ReadBodyAsync<CartCheckoutRequest>(request).ConfigureAwait(false);
            var packIds = body?.PackIds ?? [];

            var rejection = ValidateBasket(packIds);
            if (rejection is not null)
            {
                return Results.BadRequest(new { error = rejection });
            }

            return await CreateCheckoutAsync(packIds, body?.Email, body?.Embedded ?? false, db, sp, config, request).ConfigureAwait(false);
        })
        .WithName("CreateCartCheckout")
        .WithOpenApi();
    }

    /// <summary>
    /// What makes a basket unbillable before any pack is looked up. Returns the reason, or null
    /// when the basket is well-formed.
    /// </summary>
    internal static string? ValidateBasket(string[] packIds)
    {
        if (packIds.Length == 0)
        {
            return "Provide at least one pack id.";
        }
        if (packIds.Length > StripeProvider.MaxCheckoutLines)
        {
            return $"A basket carries at most {StripeProvider.MaxCheckoutLines} packs.";
        }
        if (Array.Exists(packIds, string.IsNullOrWhiteSpace))
        {
            return "A basket cannot contain a blank pack id.";
        }
        // A pack is a one-off digital download; two of the same is a client bug, and collapsing
        // it silently would charge for one while the buyer expected two.
        if (packIds.Distinct(StringComparer.Ordinal).Count() != packIds.Length)
        {
            return "A basket cannot contain the same pack twice.";
        }
        return null;
    }

    private static async Task<IResult> CreateCheckoutAsync(
        string[] packIds,
        string? buyerEmail,
        bool embedded,
        StoreDbContext db,
        IServiceProvider sp,
        IConfiguration config,
        HttpRequest request)
    {
        var packs = await LoadSellablePacksAsync(db, packIds).ConfigureAwait(false);

        // Report every id that cannot be sold, not just the first: the cart needs to prune all
        // of them in one round trip rather than fail, drop one, and fail again.
        var unavailable = packIds.Where(id => !packs.ContainsKey(id)).ToArray();
        if (unavailable.Length > 0)
        {
            return Results.NotFound(new { error = "Not available for purchase.", packIds = unavailable });
        }

        // A stub or missing price cannot produce a session — Stripe rejects it. Refusing here
        // turns an opaque provider error into an answer the storefront can act on. The buy
        // button is already gated on the same condition (pack/[id].tsx hasProvisionedPrice), so
        // this is the server-side half of a rule the client already enforces.
        var unpriced = packIds.Where(id => !HasProvisionedPrice(packs[id])).ToArray();
        if (unpriced.Length > 0)
        {
            return Results.NotFound(new { error = "Not yet priced for sale.", packIds = unpriced });
        }

        var providerName = ResolveProviderName(config, packIds.Select(id => packs[id]));
        if (providerName is null)
        {
            return Results.Problem(
                "A basket must be paid through a single payment provider; these packs use different ones.",
                statusCode: StatusCodes.Status409Conflict);
        }

        var paymentProvider = sp.GetKeyedService<IPaymentProvider>(providerName);
        if (paymentProvider is null)
        {
            return Results.Problem(
                $"Payment provider '{providerName}' is not registered.",
                statusCode: StatusCodes.Status503ServiceUnavailable);
        }

        var (successUrl, cancelUrl) = BuildRedirectUrls(packIds, config, request);

        var currency = ResolveBuyerCurrency(request, packIds.Select(id => packs[id]));

        var lines = packIds
            .Select(id => new CheckoutLine(id, packs[id].ProviderPriceId!, currency))
            .ToArray();

        var (rejection, billedLines) = ApplySmokeTestPricing(lines, packIds, sp, config, request);
        if (rejection is not null)
        {
            return rejection;
        }

        // The id the buyer's browser sent, else this request's trace id. It is stamped onto
        // the provider session here, which is the only place it can be: the webhook that
        // fulfils this purchase arrives later on a connection carrying none of these headers.
        return await OpenSessionAsync(
            paymentProvider, billedLines, buyerEmail, embedded, successUrl, cancelUrl,
            request.HttpContext.GetCorrelationId()).ConfigureAwait(false);
    }

    /// <summary>Header carrying the edge-resolved buyer country. Both apps run on Fly.io.</summary>
    /// <remarks>
    /// The same header the storefront reads to pick a shelf (Store.Web/src/lib/market.ts). The
    /// API had no server-side notion of the buyer's country at all before this — currency was a
    /// <c>const StoreCurrency = "GBP"</c> in the fulfilment fence — so a US buyer was billed in
    /// pounds however the storefront rendered the price.
    /// </remarks>
    private const string ClientCountryHeader = "Fly-Client-Country";

    /// <summary>
    /// The currency this basket is billed in, decided server-side.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Currency follows the BUYER, not the pack: a US buyer of a UK-market pack pays USD, and a
    /// UK buyer of a US-market pack pays GBP. The pack's <c>Market</c> is the jurisdiction of the
    /// opportunity and says nothing about who is holding the card.
    /// </para>
    /// <para>
    /// Resolved from the request and never from a client-supplied body field: the amount charged
    /// must not be selectable by the caller. That also means the storefront's own currency
    /// display (which reads the same header) is advisory — this is the number that bills.
    /// </para>
    /// <para>
    /// USD applies only when EVERY pack in the basket carries a <c>PriceUsdCents</c>, because
    /// that is the engine's signal that the Stripe Price was minted with a usd
    /// <c>currency_options</c> entry (bridge.py mints the two together). Opening a USD session
    /// against a Price that has no USD option is a Stripe error — a refusal to sell — so a
    /// mixed basket falls back to GBP, which every pack can always be billed in. A buyer who
    /// can pay is worth more than a buyer who sees their own currency.
    /// </para>
    /// </remarks>
    private static string ResolveBuyerCurrency(HttpRequest request, IEnumerable<Pack> packs)
    {
        var country = request.Headers[ClientCountryHeader].ToString().Trim();
        if (!string.Equals(country, "US", StringComparison.OrdinalIgnoreCase))
        {
            return "GBP";
        }
        return packs.All(p => p.PriceUsdCents is > 0) ? "USD" : "GBP";
    }

    /// <summary>
    /// Token pricing for a live-rail smoke test: returns the lines to actually bill, or a
    /// rejection that must be returned to the caller instead of opening a session.
    /// </summary>
    /// <remarks>
    /// An absent header is every real buyer and returns the lines untouched. A present-but-invalid
    /// header is REJECTED rather than sold at the listed price — falling through would bill the
    /// full amount for a mistyped test key, which is exactly what the override exists to prevent.
    /// See <see cref="SmokeTestPricing"/> for why the storefront cannot reach this.
    /// </remarks>
    private static (IResult? Rejection, IReadOnlyList<CheckoutLine> Lines) ApplySmokeTestPricing(
        IReadOnlyList<CheckoutLine> lines,
        string[] packIds,
        IServiceProvider sp,
        IConfiguration config,
        HttpRequest request)
    {
        var smoke = SmokeTestPricing.Evaluate(
            lines,
            request.Headers[SmokeTestPricing.HeaderName].ToString(),
            config["Store:InternalApiKey"] ?? Environment.GetEnvironmentVariable("STORE_INTERNAL_API_KEY"),
            config[SmokeTestPricing.PriceIdSetting] ?? Environment.GetEnvironmentVariable("STRIPE_SMOKE_TEST_PRICE_ID"));

        switch (smoke.Outcome)
        {
            case SmokeTestPricing.Outcome.Unauthorized:
                return (Results.Unauthorized(), lines);

            case SmokeTestPricing.Outcome.NotConfigured:
                return (Results.Problem(
                    $"Smoke-test pricing requested but {SmokeTestPricing.PriceIdSetting} is not configured.",
                    statusCode: StatusCodes.Status503ServiceUnavailable), lines);

            case SmokeTestPricing.Outcome.Applied:
                // Loud on purpose: a token-priced live session is the one checkout that must stay
                // greppable afterwards, so a 50p order is never mistaken for a lost £49 sale.
                sp.GetService<ILoggerFactory>()?.CreateLogger("SmokeTestPricing").LogWarning(
                    "SMOKE-TEST PRICING APPLIED: packs [{Packs}] repriced to {PriceId}",
                    string.Join(",", packIds), smoke.Lines[0].ProviderPriceId);
                // The token Price is a single hand-made Stripe object (Stripe:SmokeTestPriceId)
                // with no currency_options, so it can only be billed in its own currency. The
                // `with` rewrite above copied the buyer's currency onto it; left alone, a smoke
                // test run from a US IP would fail at Stripe and read as a broken rail rather
                // than as a misconfigured test fixture.
                return (null, [.. smoke.Lines.Select(line => line with { Currency = "GBP" })]);

            default:
                break;
        }

        return (null, smoke.Lines);
    }

    /// <summary>
    /// Open the session on the surface the storefront asked for, falling back to hosted.
    /// </summary>
    /// <remarks>
    /// Embedded first when requested; hosted otherwise, and hosted ALSO when the provider has no
    /// embedded surface (the failure case for a Stripe account
    /// without it). The fallback is not an error path — a buyer must never be unable to pay
    /// because the nicer surface was unavailable.
    /// </remarks>
    private static async Task<IResult> OpenSessionAsync(
        IPaymentProvider paymentProvider,
        IReadOnlyList<CheckoutLine> lines,
        string? buyerEmail,
        bool embedded,
        string successUrl,
        string cancelUrl,
        string? correlationId)
    {
        if (embedded)
        {
            var embeddedHandle = await paymentProvider.CreateEmbeddedCheckoutAsync(
                lines, buyerEmail, successUrl, correlationId, CancellationToken.None).ConfigureAwait(false);

            if (embeddedHandle?.ClientSecret is { Length: > 0 } secret)
            {
                return Results.Ok(new { url = embeddedHandle.Url, clientSecret = secret });
            }
        }

        var handle = await paymentProvider.CreateCheckoutAsync(
            lines, buyerEmail, successUrl, cancelUrl, correlationId, CancellationToken.None).ConfigureAwait(false);

        // `clientSecret` is always present on the wire, null on the hosted path. A field that
        // appears and disappears is how a client ends up branching on `undefined` by accident.
        return Results.Ok(new { url = handle.Url, clientSecret = (string?)null });
    }

    /// <summary>
    /// Where the provider sends the buyer afterwards.
    /// </summary>
    /// <remarks>
    /// The post-checkout redirect must land on the STOREFRONT, not on this API. /orders/success
    /// and /pack/{id} are Next.js pages; this API serves neither, so pointing the redirect at
    /// Store:PublicUrl (which PROD_DEPLOY.md sets to the API host, correctly, for magic links)
    /// sent every paying buyer to a 404. Resolution order: an explicit storefront URL, else the
    /// CORS origin — which is by definition the storefront and is already set in the runbook —
    /// else this host, which is only ever right for a single-origin local run.
    /// <para>
    /// The success page resolves the whole basket from the session id, so <c>?pack=</c> is only a
    /// convenience for the single-pack case (it renders a "back to the pack" link). A basket has
    /// no single pack to point at, and cancelling one returns to the shelf.
    /// </para>
    /// </remarks>
    private static (string SuccessUrl, string CancelUrl) BuildRedirectUrls(
        string[] packIds, IConfiguration config, HttpRequest request)
    {
        var baseUrl = DeliveryUrls.ResolveStorefrontBaseUrl(
            config["Store:StorefrontUrl"],
            Environment.GetEnvironmentVariable("STORE_STOREFRONT_URL"),
            config["Store:AllowedOrigin"],
            Environment.GetEnvironmentVariable("STORE_ALLOWED_ORIGIN"),
            $"{request.Scheme}://{request.Host}");

        var single = packIds.Length == 1 ? packIds[0] : null;
        return single is null
            ? ($"{baseUrl}/orders/success", $"{baseUrl}/")
            : ($"{baseUrl}/orders/success?pack={single}", $"{baseUrl}/pack/{single}");
    }

    /// <summary>Listed packs among the requested ids, keyed by id. Unlisted packs are absent.</summary>
    private static async Task<Dictionary<string, Pack>> LoadSellablePacksAsync(
        StoreDbContext db, string[] packIds)
    {
        var ids = packIds.Distinct(StringComparer.Ordinal).ToArray();
        var found = await db.Packs
            .Where(p => ids.Contains(p.Id) && p.IsListed)
            .ToListAsync()
            .ConfigureAwait(false);
        return found.ToDictionary(p => p.Id, StringComparer.Ordinal);
    }

    private static bool HasProvisionedPrice(Pack pack) =>
        !string.IsNullOrEmpty(pack.ProviderPriceId)
        && !pack.ProviderPriceId.StartsWith("price_stub", StringComparison.Ordinal);

    /// <summary>
    /// The provider to bill through, or null when the basket cannot agree on one. The runtime
    /// `payments:active_provider` wins when set (P7, hot switch with no redeploy); otherwise the
    /// packs' own stored provider decides, which is what keeps packs published before a switch
    /// buyable.
    /// </summary>
    internal static string? ResolveProviderName(IConfiguration config, IEnumerable<Pack> packs)
    {
        var runtimeProvider = config["payments:active_provider"];
        if (!string.IsNullOrEmpty(runtimeProvider))
        {
            return runtimeProvider;
        }

        var stored = packs
            .Select(p => string.IsNullOrEmpty(p.PaymentProvider) ? "stripe" : p.PaymentProvider)
            .Distinct(StringComparer.Ordinal)
            .ToArray();
        return stored.Length == 1 ? stored[0] : null;
    }

    /// <summary>
    /// Parse an optional JSON body. Every field on both checkout bodies is optional, so a
    /// missing, empty or malformed body is not an error — it just carries no buyer email.
    /// </summary>
    private static async Task<T?> ReadBodyAsync<T>(HttpRequest request) where T : class
    {
        if (!request.HasJsonContentType())
        {
            return null;
        }
        try
        {
            return await request.ReadFromJsonAsync<T>().ConfigureAwait(false);
        }
        catch
        {
            return null;
        }
    }
}
