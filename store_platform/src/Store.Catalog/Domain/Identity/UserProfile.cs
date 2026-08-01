namespace Store.Catalog.Domain.Identity;

/// <summary>
/// The user-editable half of an account, ported from the introduction-exchange
/// (Tie.Domain.Identity/UserProfile.cs) unchanged apart from the base class. Nothing on it was
/// marketplace-specific, so nothing needed stripping.
///
/// Kept as a separate entity rather than folded into <see cref="StoreUser"/> because these are the
/// fields a customer may freely rewrite, whereas everything on StoreUser is either Identity's
/// (password hash, security stamp, EmailConfirmed) or set by the system (TosAcceptedAt,
/// StripeCustomerId). A PUT /v1/me that maps onto one row cannot accidentally write a field that
/// gates login or order visibility.
///
/// Created lazily on first read (see GetProfileQuery) rather than in the register handler: social
/// signup, password signup and the concurrent-signup retry path would each otherwise need to
/// remember to create one, and a missing profile would surface as a null-ref on the account page.
/// </summary>
public class UserProfile : AuditableEntity
{
    protected UserProfile() : base() { }

    private UserProfile(Guid userId) : base()
    {
        UserId = userId;
        Country = "GB";
    }

    public Guid UserId { get; private set; }
    public string FirstName { get; private set; } = string.Empty;
    public string LastName { get; private set; } = string.Empty;
    public string Phone { get; private set; } = string.Empty;
    public string Bio { get; private set; } = string.Empty;
    public string Website { get; private set; } = string.Empty;
    public string AvatarUrl { get; private set; } = string.Empty;
    public string Country { get; private set; } = "GB";
    public DateTime? UpdatedAt { get; private set; }
    public DateTime? LastLogin { get; private set; }

    public static UserProfile Create(Guid userId)
    {
        if (userId == Guid.Empty) throw new ArgumentException("UserId required", nameof(userId));
        return new UserProfile(userId);
    }

    public void UpdatePersonalInfo(string firstName, string lastName, string? phone = null)
    {
        FirstName = firstName;
        LastName = lastName;
        if (phone != null) Phone = phone;
        UpdatedAt = DateTime.UtcNow;
    }

    public void UpdateProfileInfo(string? bio = null, string? website = null)
    {
        if (bio != null) Bio = bio;
        if (website != null) Website = website;
        UpdatedAt = DateTime.UtcNow;
    }

    public void SetAvatarUrl(string avatarUrl)
    {
        AvatarUrl = avatarUrl;
        UpdatedAt = DateTime.UtcNow;
    }

    /// <summary>Full replace of the user-editable profile fields (PUT /v1/me semantics).
    /// Email and username are NOT edited here — they have their own re-verified flows, and
    /// email in particular is the join key to order history.</summary>
    public void Edit(string firstName, string lastName, string phone,
        string bio, string website, string avatarUrl, string country)
    {
        FirstName = firstName;
        LastName = lastName;
        Phone = phone;
        Bio = bio;
        Website = website;
        AvatarUrl = avatarUrl;
        Country = country;
        UpdatedAt = DateTime.UtcNow;
    }

    public void RecordLogin() => LastLogin = DateTime.UtcNow;
}
