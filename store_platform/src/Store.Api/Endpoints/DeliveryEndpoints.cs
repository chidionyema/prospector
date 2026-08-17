using System.Net;
using Microsoft.EntityFrameworkCore;
using Store.Api.Payments;
using Store.Api.Services;
using Store.Catalog.Domain;
using Store.Catalog.Persistence;

namespace Store.Api.Endpoints;

/// <summary>
/// Buyer-facing delivery: the magic-link landing page and the actual download redirect.
/// Both are keyed on the opaque, non-enumerable grant token. A missing/unknown token
/// returns a generic 404 (no oracle that distinguishes "never existed" from "revoked").
/// </summary>
public static class DeliveryEndpoints
{
    // Presigned URLs are short-lived: long enough to fetch, short enough that a leaked
    // link decays fast. The entitlement, not the URL, is the durable right.
    private static readonly TimeSpan DownloadUrlTtl = TimeSpan.FromMinutes(5);

    // P1-7 — per-entitlement download cap. A magic link that leaks (forwarded email, shared
    // screenshot) must not become an unbounded mint of presigned URLs. The cap is deliberately
    // generous so legitimate re-downloads across devices never hit it; beyond it the operator
    // can re-issue. Overridable via Delivery:MaxDownloadsPerEntitlement.
    private const int DefaultMaxDownloads = 50;

    public static void MapDeliveryEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/orders/{token}", ShowOrder);
        app.MapGet("/api/orders/{token}", GetOrderJson);
        app.MapGet("/api/orders/by-session/{sessionId}", GetOrderBySession);
        app.MapGet("/download/{token}", Download);
    }

    /// <summary>
    /// Resolve a payment-provider checkout session to the entitlements it granted, so the
    /// storefront's success page can show the buyer a working download link the moment they
    /// return from payment.
    ///
    /// This exists because email was the ONLY delivery path: the success page told buyers to
    /// check their inbox, and an unconfigured mail sender failed silently, so a buyer could pay
    /// and have no route at all to what they bought. Email is now a convenience.
    ///
    /// "pending" is a normal, expected answer, not an error — the browser usually returns from
    /// the provider before the fulfilment webhook lands, so the page polls until entitlements
    /// appear. Authorisation rests on the session id being unguessable AND on the provider
    /// independently confirming the session is paid (see ResolvePaidTransactionIdAsync).
    /// </summary>
    private static async Task<IResult> GetOrderBySession(
        string sessionId,
        StoreDbContext db,
        IConfiguration config,
        IServiceProvider sp,
        ILogger<Program> logger,
        CancellationToken ct)
    {
        var providerName = config["payments:active_provider"] ?? "stripe";
        var provider = sp.GetKeyedService<IPaymentProvider>(providerName);
        if (provider is null)
        {
            return Results.NotFound();
        }

        var transactionId = await provider.ResolvePaidTransactionIdAsync(sessionId, ct)
            .ConfigureAwait(false);
        if (string.IsNullOrEmpty(transactionId))
        {
            return Pending();
        }

        var order = await db.Orders
            .FirstOrDefaultAsync(o => o.ProviderTransactionId == transactionId, ct)
            .ConfigureAwait(false);
        if (order is null)
        {
            // Paid at the provider but the webhook has not been processed yet.
            return Pending();
        }

        var entitlements = await db.Entitlements
            .Where(e => e.OrderId == order.Id)
            .ToListAsync(ct)
            .ConfigureAwait(false);

        var active = entitlements.Where(e => e.Status == EntitlementStatus.Active).ToList();

        if (active.Count == 0)
        {
            return TerminalNoDownload(order.Id, sessionId, entitlements.Count, logger);
        }

        return Results.Ok(new { status = "ready", items = await ToDownloadItemsAsync(db, active, ct).ConfigureAwait(false) });

        static IResult Pending() => Results.Ok(new { status = "pending", items = Array.Empty<object>() });
    }

    /// <summary>
    /// The order is paid but has no active entitlement, and which of the two reasons it is
    /// matters to the buyer. The distinction is knowable here and used to be thrown away as
    /// "pending", so someone whose order could NEVER be fulfilled watched the same "almost
    /// ready" spinner as someone whose webhook was half a second out — for the page's full
    /// timeout, and then got a failure message that blamed lag.
    ///
    /// FulfilmentService writes the Order in the SAME SaveChangesAsync as any entitlement it
    /// grants (FulfilmentService.cs:63-64, :105, :114), so an order with no entitlement row AT
    /// ALL is not a webhook in flight: fulfilment ran and granted nothing. Both answers here
    /// are terminal — the caller must stop polling on either.
    /// </summary>
    private static IResult TerminalNoDownload(
        long orderId, string sessionId, int entitlementCount, ILogger<Program> logger)
    {
        if (entitlementCount == 0)
        {
            logger.LogError(
                "PAID-WITHOUT-FULFILMENT shown to buyer: order {OrderId}, session {SessionId}. "
                + "Fulfilment committed with no entitlement — check the webhook handler's "
                + "unfulfilled list (underpaid line, unknown product, or missing ContentKey).",
                orderId, sessionId);
            return Results.Ok(new { status = "unfulfilled", items = Array.Empty<object>() });
        }

        // Entitlements exist but none is active: granted and later revoked by a refund or
        // dispute. Not a failure, and emphatically not "pending" — nothing further is coming.
        logger.LogInformation(
            "Order {OrderId} for session {SessionId} has only revoked entitlements.",
            orderId, sessionId);
        return Results.Ok(new { status = "revoked", items = Array.Empty<object>() });
    }

    private static async Task<List<object>> ToDownloadItemsAsync(
        StoreDbContext db,
        List<Entitlement> active,
        CancellationToken ct)
    {
        var items = new List<object>(active.Count);
        foreach (var ent in active)
        {
            var title = await db.Packs
                .Where(p => p.Id == ent.PackId)
                .Select(p => p.Title)
                .FirstOrDefaultAsync(ct)
                .ConfigureAwait(false) ?? ent.PackId;

            items.Add(new
            {
                packId = ent.PackId,
                packTitle = title,
                orderPath = $"/orders/{ent.GrantToken}",
                downloadPath = $"/download/{ent.GrantToken}",
            });
        }

        return items;
    }

    private static async Task<IResult> GetOrderJson(string token, StoreDbContext db)
    {
        var entitlement = await FindActiveAsync(db, token).ConfigureAwait(false);
        if (entitlement is null)
        {
            return Results.NotFound();
        }

        var title = await db.Packs
            .Where(p => p.Id == entitlement.PackId)
            .Select(p => p.Title)
            .FirstOrDefaultAsync()
            .ConfigureAwait(false) ?? entitlement.PackId;

        return Results.Ok(new
        {
            packId = entitlement.PackId,
            packTitle = title,
            status = entitlement.Status.ToString().ToLowerInvariant(),
            downloadPath = $"/download/{token}",
        });
    }

    private static async Task<IResult> ShowOrder(string token, StoreDbContext db)
    {
        var entitlement = await FindActiveAsync(db, token).ConfigureAwait(false);
        if (entitlement is null)
        {
            return Results.NotFound();
        }

        var title = await db.Packs
            .Where(p => p.Id == entitlement.PackId)
            .Select(p => p.Title)
            .FirstOrDefaultAsync()
            .ConfigureAwait(false) ?? entitlement.PackId;

        var safeTitle = WebUtility.HtmlEncode(title);
        var html =
            "<!doctype html><html><head><meta charset=\"utf-8\">" +
            $"<title>{safeTitle}</title></head><body>" +
            $"<h1>{safeTitle}</h1>" +
            "<p>Your purchase is ready.</p>" +
            $"<p><a href=\"/download/{WebUtility.UrlEncode(token)}\">Download now</a></p>" +
            "</body></html>";
        return Results.Content(html, "text/html");
    }

    private static async Task<IResult> Download(
        string token, StoreDbContext db, IContentStorage storage, IConfiguration config, ILogger<Program> logger)
    {
        var entitlement = await db.Entitlements
            .FirstOrDefaultAsync(e => e.GrantToken == token)
            .ConfigureAwait(false);

        if (entitlement is null)
        {
            return Results.NotFound();
        }

        // Authorize positively: only an Active entitlement may download. Checking "not
        // Revoked" would silently honour any future non-Active status (e.g. Suspended,
        // Pending) as deliverable.
        if (entitlement.Status != EntitlementStatus.Active)
        {
            return Results.StatusCode(StatusCodes.Status410Gone);
        }

        if (entitlement.ExpiresAt is { } expiry && expiry <= DateTime.UtcNow)
        {
            return Results.StatusCode(StatusCodes.Status410Gone);
        }

        // P1-7 — cap total presigned-URL mints per entitlement so a leaked link can't fan out.
        var maxDownloads = config.GetValue<int?>("Delivery:MaxDownloadsPerEntitlement") ?? DefaultMaxDownloads;
        if (entitlement.DownloadCount >= maxDownloads)
        {
            logger.LogWarning(
                "Download cap ({Cap}) reached for entitlement {PackId}; refusing further mints.",
                maxDownloads, entitlement.PackId);
            return Results.StatusCode(StatusCodes.Status429TooManyRequests);
        }

        // Serve the key snapshotted on the entitlement (what the buyer paid for). Fall back
        // to the pack's current key only for legacy entitlements that predate snapshotting.
        var contentKey = entitlement.ContentKey;
        if (string.IsNullOrEmpty(contentKey))
        {
            var pack = await db.Packs.FindAsync(entitlement.PackId).ConfigureAwait(false);
            contentKey = pack?.ContentKey;
        }

        if (string.IsNullOrEmpty(contentKey) || !storage.IsConfigured)
        {
            // Paid, valid entitlement, but content is missing or storage is down — this is
            // a deliverability failure the operator must fix, never a buyer's fault.
            logger.LogError(
                "Undeliverable download for entitlement {PackId}: contentKey={ContentKey}, storageConfigured={Configured}",
                entitlement.PackId, contentKey, storage.IsConfigured);
            return Results.StatusCode(StatusCodes.Status503ServiceUnavailable);
        }

        var url = await storage.CreatePresignedGetUrlAsync(contentKey, DownloadUrlTtl)
            .ConfigureAwait(false);

        entitlement.DownloadCount++;
        entitlement.LastDownloadedAt = DateTime.UtcNow;
        await db.SaveChangesAsync().ConfigureAwait(false);

        return Results.Redirect(url);
    }

    private static Task<Entitlement?> FindActiveAsync(StoreDbContext db, string token) =>
        db.Entitlements
            .Where(e => e.GrantToken == token && e.Status == EntitlementStatus.Active)
            .FirstOrDefaultAsync();
}
