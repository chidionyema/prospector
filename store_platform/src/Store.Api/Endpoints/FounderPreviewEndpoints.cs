using System.Security.Claims;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using Store.Api.Auth;
using Store.Api.Common.Audit;
using Store.Api.Services;
using Store.Catalog.Domain.Identity;
using Store.Catalog.Persistence;

namespace Store.Api.Endpoints;

/// <summary>
/// Founder preview: read any pack's contents without buying it — <c>GET /v1/founder/packs/{id}/download</c>.
/// </summary>
/// <remarks>
/// <para>
/// This is an IDENTITY fence, not a key fence. The obvious implementation — an
/// <c>X-Founder-Key</c> header checked against a secret — was rejected: a shared secret is a
/// bearer credential, so anyone who ever sees it (a proxy log, a curl in shell history, a
/// screenshot) becomes the founder, and nothing in the audit trail can tell them apart. The
/// requirement was "only me and no other user or account", and only an authenticated account
/// can satisfy that sentence. So the caller signs in the way every other customer does —
/// including Google, which is already live and already verifies the address
/// (<c>ExternalLoginCallbackCommand.TrustedEmailProviders</c>) — and the fence is a
/// server-side allowlist of addresses.
/// </para>
/// <para>
/// The email is resolved from the account store, never from the token's <c>email</c> claim.
/// A claim says what was true when the token was minted; an address changed or un-confirmed
/// since would keep granting access for the remaining life of that token. Same reasoning as
/// <see cref="AccountOrdersEndpoints"/>, and the same reason <see cref="IdentityUser{TKey}.EmailConfirmed"/>
/// is re-checked on every request rather than trusted from login.
/// </para>
/// <para>
/// Fail-closed by construction: an absent or empty allowlist means NOBODY is a founder. The
/// alternative default — empty means unrestricted — is how a preview endpoint ships to
/// production as a free-download hole the first time a deploy forgets a secret.
/// </para>
/// <para>
/// Deliberately NOT gated on <c>Pack.IsListed</c>. The point of the preview is to read what the
/// engine produced, and an unlisted pack (delisted by a content gate, or never listed) is
/// exactly the one worth reading. It also mints no <c>Entitlement</c> and never increments
/// <c>DownloadCount</c>: this is not a sale, and it must not look like one in the numbers or
/// consume a buyer's download cap.
/// </para>
/// <para>
/// Configure with <c>Founder:Emails</c> — a comma- or semicolon-separated list. On Fly that is
/// the secret <c>Founder__Emails</c>; the flat <c>STORE_FOUNDER_EMAILS</c> spelling is also
/// accepted so the engine's existing <c>.env</c> convention works unchanged.
/// </para>
/// </remarks>
public static class FounderPreviewEndpoints
{
    /// <summary>Short, like every other presigned link the store mints.</summary>
    private static readonly TimeSpan PreviewUrlTtl = TimeSpan.FromMinutes(5);

    private static readonly char[] AllowlistSeparators = [',', ';'];

    public static void MapFounderPreviewEndpoints(this IEndpointRouteBuilder app)
    {
        // Whether the signed-in account may use the preview at all. The storefront needs this to
        // decide whether to render the affordance; without it the only way to find out is to
        // attempt a download and read a 404, which is indistinguishable from a missing pack.
        app.MapGet("/v1/founder/me", WhoAmI).RequireAuthorization();

        app.MapGet("/v1/founder/packs/{id}/download", Download).RequireAuthorization();
    }

    private static async Task<IResult> WhoAmI(
        ClaimsPrincipal principal,
        UserManager<StoreUser> users,
        IConfiguration config)
    {
        var email = await ResolveConfirmedEmailAsync(principal, users).ConfigureAwait(false);
        return Results.Ok(new { founder = IsFounder(email, config) });
    }

    private static async Task<IResult> Download(
        string id,
        ClaimsPrincipal principal,
        UserManager<StoreUser> users,
        StoreDbContext db,
        IContentStorage storage,
        IConfiguration config,
        IAuditLogger audit,
        ILogger<Program> logger,
        CancellationToken ct)
    {
        var email = await ResolveConfirmedEmailAsync(principal, users).ConfigureAwait(false);

        if (!IsFounder(email, config))
        {
            // 404, not 403. A non-founder must not be able to learn that this route exists or
            // that a given pack id is real. The refusal is still recorded — an audit trail that
            // only holds successes cannot show an attempt.
            await audit.LogAsync(new AuditEvent
            {
                Action = AuditActions.FounderPreviewDenied,
                UserId = principal.FindFirstValue(ClaimTypes.NameIdentifier) ?? string.Empty,
                Resource = $"pack:{id}",
                IsSuccess = false,
                Details = "Account is not on the founder allowlist.",
            }, ct).ConfigureAwait(false);

            return Results.NotFound();
        }

        // No IsListed filter — see the remarks above.
        var pack = await db.Packs.FirstOrDefaultAsync(p => p.Id == id, ct).ConfigureAwait(false);
        if (pack is null)
        {
            return Results.NotFound();
        }

        if (string.IsNullOrEmpty(pack.ContentKey) || !storage.IsConfigured)
        {
            logger.LogError(
                "Founder preview undeliverable for pack {PackId}: contentKey={ContentKey}, storageConfigured={Configured}",
                id, pack.ContentKey, storage.IsConfigured);
            return Results.StatusCode(StatusCodes.Status503ServiceUnavailable);
        }

        // The pack's CURRENT key, deliberately: a buyer gets the bytes they paid for
        // (Entitlement.ContentKey, snapshotted), but a preview exists to show what the pack is
        // NOW, including a rebuild that has not reached any existing buyer.
        var url = await storage.CreatePresignedGetUrlAsync(pack.ContentKey, PreviewUrlTtl)
            .ConfigureAwait(false);

        await audit.LogAsync(new AuditEvent
        {
            Action = AuditActions.FounderPreview,
            UserId = principal.FindFirstValue(ClaimTypes.NameIdentifier) ?? string.Empty,
            Resource = $"pack:{id}",
            IsSuccess = true,
            Details = $"Presigned preview minted for contentKey={pack.ContentKey}.",
        }, ct).ConfigureAwait(false);

        return Results.Redirect(url);
    }

    /// <summary>The account's confirmed address, or null if there is no usable identity.</summary>
    private static async Task<string?> ResolveConfirmedEmailAsync(
        ClaimsPrincipal principal, UserManager<StoreUser> users)
    {
        var id = principal.FindFirstValue(ClaimTypes.NameIdentifier) ?? principal.FindFirstValue("sub");
        if (string.IsNullOrEmpty(id))
        {
            return null;
        }

        var user = await users.FindByIdAsync(id).ConfigureAwait(false);

        // Unconfirmed means the address was typed, not proven. Allowlisting an address that
        // anyone may claim would turn the fence into the shared secret it exists to avoid.
        return user is { EmailConfirmed: true } && !string.IsNullOrEmpty(user.Email)
            ? user.Email
            : null;
    }

    private static bool IsFounder(string? email, IConfiguration config)
    {
        if (string.IsNullOrEmpty(email))
        {
            return false;
        }

        var raw = config["Founder:Emails"] ?? config["STORE_FOUNDER_EMAILS"];
        if (string.IsNullOrWhiteSpace(raw))
        {
            return false;
        }

        // Case-insensitive: mailbox case is not significant at any provider the store trusts,
        // and "Chidi@…" failing while "chidi@…" works is a bug, not a fence.
        var entries = raw.Split(
            AllowlistSeparators, StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

        return Array.Exists(entries, entry => string.Equals(entry, email, StringComparison.OrdinalIgnoreCase));
    }
}
