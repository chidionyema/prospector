using System.Security.Claims;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using Store.Catalog.Domain;
using Store.Catalog.Domain.Identity;
using Store.Catalog.Persistence;

namespace Store.Api.Auth;

/// <summary>
/// Order history for the signed-in customer: <c>GET /v1/auth/me/orders</c>.
/// </summary>
/// <remarks>
/// Kept out of <see cref="AuthEndpoints"/> on purpose. Everything in that file came across from
/// the-introduction-exchange and is deliberately still diffable against it, so a security fix
/// made upstream can be re-synced by reading a diff rather than a rewrite. This endpoint has no
/// upstream counterpart — TIE had no orders — so putting it there would poison that property.
///
/// <para>
/// The join is <see cref="Order.BuyerEmail"/> to the account's email STRING. There is no UserId
/// column on an order, by design: people buy before they ever create an account, and a purchase
/// made as a guest must still appear the moment they register with the same address.
/// </para>
/// <para>
/// That design is exactly why <see cref="IdentityUser{TKey}.EmailConfirmed"/> is checked here and
/// not merely at login. Verification is the ONLY thing standing between a customer's purchase
/// history and anyone who can type their address, and re-checking it on every read means an
/// account whose address is unconfirmed after the fact — an operator action, an email change —
/// stops seeing orders immediately rather than for the remaining life of its access token.
/// </para>
/// </remarks>
public static class AccountOrdersEndpoints
{
    public static void MapAccountOrdersEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/v1/auth/me/orders", GetMyOrders).RequireAuthorization();
    }

    private static async Task<IResult> GetMyOrders(
        ClaimsPrincipal principal,
        UserManager<StoreUser> users,
        StoreDbContext db,
        CancellationToken ct)
    {
        // Resolved from the store, not from a claim in the token. The email claim was minted when
        // the token was issued and says what was true then; an address changed or unconfirmed
        // since would keep serving the previous owner's orders until the token expired.
        var user = await users.FindByIdAsync(principal.UserId().ToString()).ConfigureAwait(false);
        if (user is null || string.IsNullOrEmpty(user.Email))
        {
            return Results.Ok(new { email_confirmed = false, orders = Array.Empty<object>() });
        }

        if (!user.EmailConfirmed)
        {
            // 200 with an empty list and the flag, not 403: the account page needs to render the
            // "verify your address to see your orders" state, and a 403 would be indistinguishable
            // from a session that had simply expired.
            return Results.Ok(new { email_confirmed = false, orders = Array.Empty<object>() });
        }

        var email = user.Email;
        var orders = await db.Orders
            .Where(o => o.BuyerEmail == email)
            .OrderByDescending(o => o.CreatedAt)
            .ToListAsync(ct)
            .ConfigureAwait(false);

        if (orders.Count == 0)
        {
            return Results.Ok(new { email_confirmed = true, orders = Array.Empty<object>() });
        }

        // One query for every entitlement across every order, then grouped in memory. The
        // alternative — a query per order — is the N+1 that turns a customer with a long history
        // into a slow page, and SQLite is a single writer, so the extra round-trips are not free.
        var orderIds = orders.ConvertAll(o => o.Id);
        var entitlements = await db.Entitlements
            .Where(e => orderIds.Contains(e.OrderId))
            .ToListAsync(ct)
            .ConfigureAwait(false);

        var packIds = entitlements.ConvertAll(e => e.PackId).Distinct(StringComparer.Ordinal).ToList();
        var titles = await db.Packs
            .Where(p => packIds.Contains(p.Id))
            .ToDictionaryAsync(p => p.Id, p => p.Title, StringComparer.Ordinal, ct)
            .ConfigureAwait(false);

        var payload = orders.ConvertAll(order => new
        {
            id = order.Id,
            created_at = order.CreatedAt,
            amount_pence = order.AmountPence,
            currency = order.Currency,
            status = order.Status.ToString().ToLowerInvariant(),
            items = entitlements
                .Where(e => e.OrderId == order.Id)
                .Select(e => new
                {
                    pack_id = e.PackId,
                    pack_title = titles.GetValueOrDefault(e.PackId, e.PackId),
                    status = e.Status.ToString().ToLowerInvariant(),
                    // Only an Active entitlement gets a link. A refunded or disputed purchase stays
                    // visible in the history — the customer did buy it — but hands out no download,
                    // which is what /download/{token} would enforce anyway (DeliveryEndpoints.cs:219).
                    download_path = e.Status == EntitlementStatus.Active ? $"/download/{e.GrantToken}" : null,
                })
                .ToList(),
        });

        return Results.Ok(new { email_confirmed = true, orders = payload });
    }
}
