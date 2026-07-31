using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using Store.Api.Contracts;
using Store.Catalog.Domain;
using Store.Catalog.Persistence;

namespace Store.Api.Services;

/// <summary>
/// Captures a waitlist signup and the consent evidence that makes it lawful to hold.
///
/// Three rules this type exists to enforce, all of them the reason the logic is here rather
/// than inline in an endpoint lambda where they could not be tested:
///
/// 1. <b>Consent is validated server-side.</b> An unticked box in the browser is a UI
///    affordance, not a control. The request is rejected when <c>Consent</c> is not true.
/// 2. <b>The consent hash is computed here, never accepted from the client.</b> A
///    client-supplied hash proves only that the client can hash; the point of the evidence is
///    to show what was actually rendered to the person, so the server hashes the text it was
///    sent and stores that.
/// 3. <b>The IP is salted and hashed, never persisted raw.</b> The purpose is making
///    rate-limit abuse investigable, which does not need the address itself.
///
/// Nothing here sends email. The correct Mailjet contracting entity is still unresolved in the
/// privacy notice's sub-processor list, and naming the wrong one would be a false statement in
/// a UK GDPR notice. Capture now; sending is a separate story.
/// </summary>
public sealed class WaitlistService(StoreDbContext db, string ipHashSalt)
{
    /// <summary>
    /// The wording version shipped with this release. Stored alongside the hash so a later
    /// change to the sentence is distinguishable in the evidence rather than silently merged.
    /// </summary>
    public const string CurrentConsentVersion = "waitlist-2026-07-30";

    /// <summary>RFC 5321 maximum address length — matches the column width in StoreDbContext.</summary>
    private const int MaxEmailLength = 320;

    private const int MaxQueryLength = 500;

    /// <summary>SHA-256 of the exact sentence the person was shown, lower-case hex.</summary>
    public static string HashConsentText(string consentText)
        => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(consentText))).ToLowerInvariant();

    /// <summary>
    /// Salted SHA-256 of a client IP, lower-case hex. Null in, null out — a request with no
    /// resolvable address stores no address, rather than a hash of the string "unknown"
    /// which would collide every such caller into one bucket and look like a real identity.
    /// </summary>
    public static string? HashIp(string? ip, string salt)
    {
        if (string.IsNullOrWhiteSpace(ip)) return null;
        var bytes = Encoding.UTF8.GetBytes(string.Concat(salt, ":", ip));
        return Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    }

    /// <summary>
    /// Minimal structural email check. Deliberately not an RFC 5322 regex: the address is never
    /// used to authenticate anyone, only to send one message if a pack ships, so an
    /// over-strict rule that rejects a valid unusual address costs more than it saves.
    /// </summary>
    public static bool LooksLikeEmail(string email)
    {
        if (string.IsNullOrWhiteSpace(email) || email.Length > MaxEmailLength) return false;
        var at = email.IndexOf('@', StringComparison.Ordinal);
        if (at <= 0 || at != email.LastIndexOf('@')) return false;
        var domain = email[(at + 1)..];
        return domain.Contains('.', StringComparison.Ordinal)
               && !domain.StartsWith('.')
               && !domain.EndsWith('.')
               && !email.Contains(' ', StringComparison.Ordinal);
    }

    /// <summary>
    /// Validate, build the evidence, and persist. Returns a rejection rather than throwing so
    /// the endpoint can turn it straight into a 400 naming the offending field.
    /// </summary>
    public async Task<WaitlistResult> SignUpAsync(
        WaitlistRequest request,
        string? clientIp,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);

        var email = (request.Email ?? string.Empty).Trim();
        if (!LooksLikeEmail(email))
        {
            return WaitlistResult.Rejected("email: a valid email address is required.");
        }

        // The hard gate. Consent that was not given cannot be inferred from the fact that a
        // request arrived — a pre-ticked or absent box is not consent under UK GDPR.
        if (!request.Consent)
        {
            return WaitlistResult.Rejected(
                "consent: you must tick the consent box before we can store your email address.");
        }

        var consentText = (request.ConsentText ?? string.Empty).Trim();
        if (consentText.Length == 0)
        {
            return WaitlistResult.Rejected(
                "consentText: the exact consent wording shown must be sent so it can be recorded as evidence.");
        }

        var query = string.IsNullOrWhiteSpace(request.Query)
            ? null
            : request.Query.Trim()[..Math.Min(request.Query.Trim().Length, MaxQueryLength)];

        var signup = new WaitlistSignup
        {
            Id = Guid.NewGuid().ToString("N", CultureInfo.InvariantCulture),
            Email = email,
            Query = query,
            ConsentVersion = string.IsNullOrWhiteSpace(request.ConsentVersion)
                ? CurrentConsentVersion
                : request.ConsentVersion.Trim(),
            ConsentTextHash = HashConsentText(consentText),
            IpHash = HashIp(clientIp, ipHashSalt),
            Source = string.IsNullOrWhiteSpace(request.Source) ? null : request.Source.Trim(),
            CreatedAt = DateTime.UtcNow,
        };

        db.WaitlistSignups.Add(signup);
        await db.SaveChangesAsync(cancellationToken).ConfigureAwait(false);
        return WaitlistResult.Accepted(signup);
    }
}
