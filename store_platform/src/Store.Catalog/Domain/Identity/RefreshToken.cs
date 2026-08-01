using System.ComponentModel.DataAnnotations;

namespace Store.Catalog.Domain.Identity;

/// <summary>
/// Refresh token, ported verbatim from the introduction-exchange
/// (Tie.Domain.Identity/RefreshToken.cs) apart from the base class.
///
/// <see cref="FamilyId"/> is the load-bearing field: every rotation of a token keeps the
/// family id of the token it replaced, so a whole login session is one family. Presenting an
/// already-used token is the signature of a stolen token being replayed, and the service
/// answers by revoking the entire family rather than just that row — otherwise the thief and
/// the victim would simply take turns refreshing.
/// </summary>
public class RefreshToken : AuditableEntity
{
    protected RefreshToken() : base() { }

    private RefreshToken(Guid userId, string token, DateTime expires, Guid familyId, string? userAgent = null) : base()
    {
        UserId = userId;
        Token = token;
        Expires = expires;
        FamilyId = familyId;
        CreatedUserAgent = userAgent;
    }

    public Guid UserId { get; private set; }
    public string Token { get; private set; } = string.Empty;
    public DateTime Expires { get; private set; }
    public Guid FamilyId { get; private set; }
    public bool IsUsed { get; private set; }
    public bool IsRevoked { get; private set; }
    public string? ReplacedByToken { get; private set; }
    public string? CreatedUserAgent { get; private set; }

    /// <summary>JTI of the access token issued alongside this refresh token, so logout can
    /// deny-list that access token instead of waiting out its expiry.</summary>
    public string? AccessTokenJti { get; set; }

    public static RefreshToken Create(Guid userId, string token, DateTime expires, Guid? familyId = null, string? userAgent = null)
    {
        if (userId == Guid.Empty) throw new ArgumentException("UserId required", nameof(userId));
        ArgumentException.ThrowIfNullOrWhiteSpace(token);
        return new RefreshToken(userId, token, expires, familyId ?? Guid.NewGuid(), userAgent);
    }

    public bool IsExpired => DateTime.UtcNow >= Expires;
    public bool IsActive => !IsUsed && !IsRevoked && !IsExpired;

    public void MarkAsUsed(string replacedByToken)
    {
        IsUsed = true;
        ReplacedByToken = replacedByToken;
    }

    public void Revoke() => IsRevoked = true;
}
