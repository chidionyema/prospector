using Microsoft.EntityFrameworkCore;
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
            return await CreateCheckoutAsync([id], body?.Email, db, sp, config, request).ConfigureAwait(false);
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

            return await CreateCheckoutAsync(packIds, body?.Email, db, sp, config, request).ConfigureAwait(false);
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

        var lines = packIds
            .Select(id => new CheckoutLine(id, packs[id].ProviderPriceId!))
            .ToArray();

        var handle = await paymentProvider.CreateCheckoutAsync(
            lines, buyerEmail, successUrl, cancelUrl, CancellationToken.None).ConfigureAwait(false);

        return Results.Ok(new { url = handle.Url });
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
            .Select(p => string.IsNullOrEmpty(p.PaymentProvider) ? "paddle" : p.PaymentProvider)
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
