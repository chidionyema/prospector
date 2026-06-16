using System.Net;
using Microsoft.EntityFrameworkCore;
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

    public static void MapDeliveryEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/orders/{token}", ShowOrder);
        app.MapGet("/download/{token}", Download);
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
        string token, StoreDbContext db, IContentStorage storage, ILogger<Program> logger)
    {
        var entitlement = await db.Entitlements
            .FirstOrDefaultAsync(e => e.GrantToken == token)
            .ConfigureAwait(false);

        if (entitlement is null)
        {
            return Results.NotFound();
        }

        if (entitlement.Status == EntitlementStatus.Revoked)
        {
            return Results.StatusCode(StatusCodes.Status410Gone);
        }

        if (entitlement.ExpiresAt is { } expiry && expiry <= DateTime.UtcNow)
        {
            return Results.StatusCode(StatusCodes.Status410Gone);
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
