using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using Microsoft.AspNetCore.Http;
using Microsoft.IdentityModel.Tokens;
using Store.Catalog.Domain.Identity;

namespace Store.Api.Identity;

/// <summary>JWT generation/validation. Ported from haworks Identity.Application/Interfaces/IJwtTokenService.cs.</summary>
public interface IJwtTokenService
{
    Task<JwtSecurityToken> GenerateTokenAsync(StoreUser user, DateTime expiration, CancellationToken ct = default);
    Task<ClaimsPrincipal?> ValidateTokenAsync(string tokenString, bool validateLifetime = true, CancellationToken ct = default);
    TokenValidationParameters GetTokenValidationParameters(bool validateLifetime = true);
    void SetSecureCookie(HttpContext context, JwtSecurityToken token);
    void SetSecureCookie(HttpContext context, string tokenString);
    void DeleteAuthCookie(HttpContext context);
}

/// <summary>Refresh-token lifecycle. Ported from haworks Identity.Application/Interfaces/IRefreshTokenService.cs.</summary>
public interface IRefreshTokenService
{
    Task<RefreshToken> GenerateRefreshTokenAsync(string userId, string? userAgent = null, string? ipAddress = null, string? accessTokenJti = null, CancellationToken ct = default);
    Task<RefreshToken> GenerateRefreshTokenAsync(string userId, Guid? familyId, string? userAgent = null, string? ipAddress = null, string? accessTokenJti = null, CancellationToken ct = default);
    Task RevokeRefreshTokensForUserAsync(string userId, CancellationToken ct = default);

    /// <summary>
    /// Atomically consumes one specific refresh token and issues a new one in the same family.
    /// If the token was already used, it revokes the entire family (reuse detection).
    /// </summary>
    Task<(bool Success, RefreshToken? NewToken)> RotateRefreshTokenAsync(string token, string? userAgent = null, string? ipAddress = null, string? accessTokenJti = null, CancellationToken ct = default);
}

/// <summary>JTI revocation list. Ported from haworks Identity.Application/Interfaces/ITokenRevocationService.cs.</summary>
public interface ITokenRevocationService
{
    Task RevokeTokenAsync(string tokenValue, string userId, DateTime expiryDate, CancellationToken ct = default);
    Task<bool> IsTokenRevokedAsync(string tokenValue, CancellationToken ct = default);
}

/// <summary>Provides the RSA signing key for RS256 JWTs + the public JWK for JWKS. Config-backed (no Vault).</summary>
public interface IJwtSigningKeyProvider
{
    string KeyId { get; }
    RsaSecurityKey SigningKey { get; }
    JsonWebKey PublicJwk { get; }
}
