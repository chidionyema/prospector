using System.Security.Claims;

namespace Store.Api.Auth;

/// <summary>Small API-layer helpers for identity.</summary>
public static class AuthExtensions
{
    /// <summary>The authenticated user's id, sourced from the JWT claim (never a header/body).</summary>
    public static Guid UserId(this ClaimsPrincipal user)
    {
        var id = user.FindFirstValue(ClaimTypes.NameIdentifier) ?? user.FindFirstValue("sub");
        return Guid.TryParse(id, out var g)
            ? g
            : throw new UnauthorizedAccessException("Authenticated principal has no valid user id claim.");
    }

    // SeedRolesAsync is deliberately not ported. The introduction-exchange seeded Buyer/Connector
    // at startup so register-time role assignment would succeed; the store has exactly one kind of
    // account, so there is nothing to seed and no role to assign. The AspNetRoles/AspNetUserRoles
    // tables still exist because IdentityDbContext creates them — they stay empty, which is the
    // cheapest correct answer. Dropping them would mean overriding Identity's model for no gain.
}
