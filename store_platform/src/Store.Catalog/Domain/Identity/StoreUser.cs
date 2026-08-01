using Microsoft.AspNetCore.Identity;

namespace Store.Catalog.Domain.Identity;

/// <summary>
/// A store customer account. Written fresh rather than ported: the introduction-exchange's
/// User carries marketplace concerns a storefront has no use for — KycLevel, VerificationTier,
/// StripeAccountId and PayoutReady (Connector payouts, this store has none), and
/// NormalizedEmailKey (anti-Sybil matching, which matters when money moves *between* users).
///
/// Deliberately NOT joined to <see cref="Order"/> or <see cref="Entitlement"/> by foreign key.
/// Both of those key purchases on a plain <c>BuyerEmail</c> string, written by the payment
/// webhook long before any account exists. Matching on the verified email instead means every
/// past guest purchase appears the moment its owner registers, with no backfill migration and
/// no orphan rows.
///
/// The safety of that join rests entirely on <see cref="Microsoft.AspNetCore.Identity.IdentityUser{TKey}.EmailConfirmed"/>:
/// an unverified account claiming an email must never be shown that email's order history.
/// Verification gates the account pages, not just login.
/// </summary>
public class StoreUser : IdentityUser<Guid>
{
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public DateTime? UpdatedAt { get; set; }

    /// <summary>Soft disable. Kept separate from Identity's lockout, which is transient and
    /// automatic (failed-password backoff); this one is an operator decision.</summary>
    public bool IsActive { get; set; } = true;

    /// <summary>Version of the terms accepted, paired with when. Together they answer
    /// "who accepted what, when" without a separate consent log.</summary>
    public string? TosVersionAccepted { get; set; }
    public DateTime? TosAcceptedAt { get; set; }

    /// <summary>Set only if this customer is later linked to a Stripe Customer object.
    /// Checkout does not create one today (StripeProvider reads the email off the session),
    /// so this stays null until saved payment methods are wanted.</summary>
    public string? StripeCustomerId { get; set; }

    public void AcceptTos(string version, DateTime acceptedAtUtc)
    {
        TosVersionAccepted = version;
        TosAcceptedAt = acceptedAtUtc;
        UpdatedAt = DateTime.UtcNow;
    }
}
