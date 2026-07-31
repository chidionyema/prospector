namespace Store.Catalog.Domain;

/// <summary>
/// One person asking to be told if a vetted pack ever ships in a space we do not cover.
///
/// This row is consent evidence, not a mailing list. Under UK GDPR the lawful basis here is
/// consent, and consent is only defensible if we can show *what* the person was shown when
/// they gave it — so the exact consent sentence is versioned and hashed alongside the
/// timestamp. A bare boolean "they ticked the box" proves nothing a year later.
///
/// The IP is stored only as a salted hash: it is retained to make rate-limit abuse
/// investigable, which does not require knowing the address itself. Storing it raw would be
/// more personal data than the purpose needs.
///
/// Nothing in this type sends email. The sub-processor list in the privacy notice carries an
/// unresolved question about the correct Mailjet contracting entity, and naming the wrong one
/// would be a false statement in a UK GDPR notice. Capture now, send in a separate story.
/// </summary>
public class WaitlistSignup
{
    public required string Id { get; set; }

    public required string Email { get; set; }

    /// <summary>What they were searching for when nothing matched — this is the demand signal.</summary>
    public string? Query { get; set; }

    /// <summary>Identifier of the consent wording shown, so a later change is distinguishable.</summary>
    public required string ConsentVersion { get; set; }

    /// <summary>SHA-256 of the exact consent sentence rendered to this person.</summary>
    public required string ConsentTextHash { get; set; }

    /// <summary>Salted SHA-256 of the client IP. The raw address is never persisted.</summary>
    public string? IpHash { get; set; }

    /// <summary>Which surface captured it (e.g. "catalog-empty-state"), for funnel attribution.</summary>
    public string? Source { get; set; }

    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}
