using System.Security.Cryptography;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Store.Api.Identity;
using Store.Catalog.Domain.Identity;
using Store.Api.Persistence;
using Store.Catalog.Persistence;

namespace Store.Api.Identity;

/// <summary>
/// Refresh-token lifecycle + read-side lookup. Implements chain-based rotation
/// and reuse detection (family revocation) as per E01-004.
/// </summary>
public sealed class RefreshTokenService : IRefreshTokenService, IRefreshTokenReader
{
    private readonly StoreDbContext _context;
    private readonly JwtOptions _jwtOptions;
    private readonly ILogger<RefreshTokenService> _logger;

    public RefreshTokenService(
        StoreDbContext context,
        IOptions<JwtOptions> jwtOptions,
        ILogger<RefreshTokenService> logger)
    {
        _context = context;
        _jwtOptions = jwtOptions.Value;
        _logger = logger;
    }

    public Task<RefreshToken> GenerateRefreshTokenAsync(string userId, string? userAgent = null, string? ipAddress = null, string? accessTokenJti = null, CancellationToken ct = default)
    {
        return GenerateRefreshTokenAsync(userId, null, userAgent, ipAddress, accessTokenJti, ct);
    }

    public async Task<RefreshToken> GenerateRefreshTokenAsync(string userId, Guid? familyId, string? userAgent = null, string? ipAddress = null, string? accessTokenJti = null, CancellationToken ct = default)
    {
        var value = Convert.ToBase64String(RandomNumberGenerator.GetBytes(64));
        var expires = DateTime.UtcNow.AddDays(_jwtOptions.RefreshTokenExpiryDays);
        var refreshToken = RefreshToken.Create(Guid.Parse(userId), value, expires, familyId, userAgent);
        refreshToken.CreatedFromIp = ipAddress;
        refreshToken.AccessTokenJti = accessTokenJti;

        _context.RefreshTokens.Add(refreshToken);
        await _context.SaveChangesAsync(ct).ConfigureAwait(false);

        _logger.LogInformation("Refresh token generated for user {UserId} in family {FamilyId}", userId, refreshToken.FamilyId);
        return refreshToken;
    }

    public async Task RevokeRefreshTokensForUserAsync(string userId, CancellationToken ct = default)
    {
        if (!Guid.TryParse(userId, out var uid)) return;
        var deleted = await _context.RefreshTokens.Where(rt => rt.UserId == uid).ExecuteDeleteAsync(ct).ConfigureAwait(false);
        if (deleted != 0)
            _logger.LogInformation("Revoked {Count} refresh tokens for user {UserId}", deleted, userId);
    }

    public async Task<(bool Success, RefreshToken? NewToken)> RotateRefreshTokenAsync(string token, string? userAgent = null, string? ipAddress = null, string? accessTokenJti = null, CancellationToken ct = default)
    {
        var stored = await _context.RefreshTokens.FirstOrDefaultAsync(rt => rt.Token == token, ct).ConfigureAwait(false);
        if (stored == null || stored.IsRevoked || stored.IsExpired)
        {
            return (false, null);
        }

        if (stored.IsUsed)
        {
            // REUSE DETECTED: Revoke the entire family
            _logger.LogWarning("Refresh token reuse detected for family {FamilyId}. Revoking family.", stored.FamilyId);
            await _context.RefreshTokens
                .Where(rt => rt.FamilyId == stored.FamilyId)
                .ExecuteUpdateAsync(s => s.SetProperty(rt => rt.IsRevoked, true), ct).ConfigureAwait(false);
            return (false, null);
        }

        // Valid rotation
        var newTokenValue = Convert.ToBase64String(RandomNumberGenerator.GetBytes(64));
        var expires = DateTime.UtcNow.AddDays(_jwtOptions.RefreshTokenExpiryDays);
        var newToken = RefreshToken.Create(stored.UserId, newTokenValue, expires, stored.FamilyId, userAgent);
        newToken.CreatedFromIp = ipAddress;
        newToken.AccessTokenJti = accessTokenJti;

        stored.MarkAsUsed(newTokenValue);
        _context.RefreshTokens.Add(newToken);
        
        await _context.SaveChangesAsync(ct).ConfigureAwait(false);
        return (true, newToken);
    }

    public Task<RefreshToken?> FindAsync(string token, CancellationToken ct = default) =>
        _context.RefreshTokens.FirstOrDefaultAsync(rt => rt.Token == token, ct);
}
