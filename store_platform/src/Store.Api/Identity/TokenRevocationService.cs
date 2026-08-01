using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Caching.Memory;
using Microsoft.Extensions.Logging;
using Store.Api.Identity;
using Store.Catalog.Domain.Identity;

using Store.Api.Persistence;
using Store.Catalog.Persistence;

namespace Store.Api.Identity;

/// <summary>
/// JTI revocation list. Ported from haworks Identity.Infrastructure/
/// TokenRevocationService.cs, with IHybridCache (L1+Redis) swapped for the lean
/// IMemoryCache (single-process, no Redis). DB is the source of truth; the cache
/// is a fast-path for repeat checks.
/// </summary>
public sealed class TokenRevocationService : ITokenRevocationService
{
    private readonly StoreDbContext _context;
    private readonly IMemoryCache _cache;
    private readonly ILogger<TokenRevocationService> _logger;

    private const string CachePrefix = "revoked_token:";

    public TokenRevocationService(StoreDbContext context, IMemoryCache cache, ILogger<TokenRevocationService> logger)
    {
        _context = context;
        _cache = cache;
        _logger = logger;
    }

    public async Task RevokeTokenAsync(string tokenValue, string userId, DateTime expiryDate, CancellationToken ct = default)
    {
        if (string.IsNullOrEmpty(tokenValue) || string.IsNullOrEmpty(userId)) return;
        if (await IsTokenRevokedAsync(tokenValue, ct).ConfigureAwait(false)) return;

        var uid = Guid.TryParse(userId, out var g) ? g : (Guid?)null;
        _context.RevokedTokens.Add(RevokedToken.Create(tokenValue, expiryDate, "Manual revocation", uid));
        await _context.SaveChangesAsync(ct).ConfigureAwait(false);
        CacheRevocation(tokenValue, expiryDate);
        _logger.LogInformation("Token revoked for user {UserId}", userId);
    }

    public async Task<bool> IsTokenRevokedAsync(string tokenValue, CancellationToken ct = default)
    {
        if (string.IsNullOrEmpty(tokenValue)) return false;
        if (_cache.TryGetValue(CachePrefix + tokenValue, out _)) return true;

        var isRevoked = await _context.RevokedTokens.AnyAsync(rt => rt.Token == tokenValue, ct).ConfigureAwait(false);
        if (isRevoked)
        {
            var expiry = await _context.RevokedTokens
                .Where(rt => rt.Token == tokenValue)
                .Select(rt => rt.ExpiresAt)
                .FirstOrDefaultAsync(ct).ConfigureAwait(false);
            CacheRevocation(tokenValue, expiry);
        }
        return isRevoked;
    }

    private void CacheRevocation(string tokenValue, DateTime expiryDate)
    {
        var ttl = expiryDate > DateTime.UtcNow ? expiryDate - DateTime.UtcNow : TimeSpan.FromMinutes(5);
        _cache.Set(CachePrefix + tokenValue, true, ttl);
    }
}
