using System.ComponentModel.DataAnnotations;

namespace Store.Api.Identity;

/// <summary>JWT config. Ported from haworks Identity.Application/Options/JwtOptions.cs (key-ring fields dropped — no Vault).</summary>
public sealed class JwtOptions
{
    public const string SectionName = "Jwt";

    public string Issuer { get; set; } = string.Empty;
    public string Audience { get; set; } = string.Empty;

    /// <summary>RSA private key (PEM, raw or base64). Replaces the Vault key ring.</summary>
    public string SigningKeyPem { get; set; } = string.Empty;
    public string KeyId { get; set; } = "config-1";

    // Upper bound widened to 24h (was 60) so the D-64 interim Jwt__TokenExpiryMinutes=720 set in
    // dotnet/fly.toml is a VALID value — a long-lived access token is safe here because
    // OnTokenValidated re-checks the JTI revocation list on every request (logout stays instant).
    // Proper refresh-token rotation + short access tokens is the post-beta follow-up (D-64).
    [Range(5, 1440)]
    public int TokenExpiryMinutes { get; set; } = 15;

    [Range(1, 90)]
    public int RefreshTokenExpiryDays { get; set; } = 7;
}

/// <summary>Auth-related constants, ported from haworks Identity.Application/Constants/AuthConstants.cs.</summary>
public static class AuthConstants
{
    /// <summary>Tolerance for clock drift between the token issuer and this validator.</summary>
    public const int ClockSkewToleranceSeconds = 30;

    /// <summary>
    /// How long a lockout lasts, quoted back to the user in the "try again in N minutes" message
    /// (LoginCommand.cs:69,77). It MUST equal the LockoutOptions.DefaultLockoutTimeSpan configured
    /// in DI — that is the value Identity actually enforces; this one only phrases it.
    /// </summary>
    public const int LockoutDurationMinutes = 15;

    // RolePendingClaim, AllRoles and MaxFailedLoginAttempts are deliberately not ported. The first
    // two encode the introduction-exchange's Buyer/Connector split, which the store does not have —
    // see JwtTokenService.GenerateTokenAsync for why no role claim is emitted at all. The third was
    // already dead there: nothing read it, because Identity enforces the threshold itself.
}
