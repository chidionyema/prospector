using System.ComponentModel.DataAnnotations;

namespace Store.Catalog.Domain.Identity;

/// <summary>
/// JTI deny-list entry. A JWT is valid until it expires, so logout and session-revoke need a
/// place to record "this specific access token is dead" for the remainder of its short life.
/// <see cref="ExpiresAt"/> is what makes the table self-limiting: once the token would have
/// expired anyway, the row is meaningless and <see cref="CanBeCleanedUp"/> is true.
/// </summary>
public class RevokedToken : AuditableEntity
{
    protected RevokedToken() : base() { }

    private RevokedToken(string token, DateTime revokedAt, DateTime expiresAt, string? reason, Guid? userId) : base()
    {
        Token = token;
        RevokedAt = revokedAt;
        ExpiresAt = expiresAt;
        Reason = reason;
        UserId = userId;
    }

    [Required]
    [MaxLength(500)]
    public string Token { get; private set; } = string.Empty;

    [Required]
    public DateTime RevokedAt { get; private set; }

    [MaxLength(200)]
    public string? Reason { get; private set; }

    /// <summary>Nullable: a token can be revoked without resolving its owner.</summary>
    public Guid? UserId { get; private set; }

    public DateTime ExpiresAt { get; private set; }

    public static RevokedToken Create(string token, DateTime expiresAt, string? reason = null, Guid? userId = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(token);
        return new RevokedToken(token, DateTime.UtcNow, expiresAt, reason, userId);
    }

    public bool CanBeCleanedUp => DateTime.UtcNow >= ExpiresAt;
}
