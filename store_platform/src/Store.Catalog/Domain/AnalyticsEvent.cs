namespace Store.Catalog.Domain;

/// <summary>
/// One anonymous storefront interaction: a page view, a hero CTA click, a completed checkout.
///
/// This table exists to answer one question — "does the storefront convert, and at what
/// volume?" — because until it can be answered, no copy test is measurable. It is a tally,
/// not a profile: no IP, no user agent, no cookie, no email, and no visitor identifier of
/// any kind.
///
/// It carried a client-minted SessionId for one hour on 2026-07-31 before that column was
/// dropped. Two reasons, and both are standing rules for anything added here: (1) no report
/// ever read it — a field nothing consumes is pure liability; (2) minting it required writing
/// to the visitor's device, which PECR reg 6(1) forbids without consent (the wording is
/// "store information ... in the terminal equipment", so sessionStorage counts, not just
/// cookies) and this site has no consent UI. Adding a per-visitor id here means adding a
/// consent banner first.
/// </summary>
public class AnalyticsEvent
{
    public long Id { get; set; }

    /// <summary>Event name from the server-side allowlist (e.g. "page_view"). Never free text.</summary>
    public required string Name { get; set; }

    /// <summary>Pathname only (e.g. "/pack/abc") — never query strings, which can carry tokens.</summary>
    public string? Path { get; set; }

    /// <summary>
    /// Small event-specific detail. For "checkout_completed" this is the payment provider's
    /// checkout session id, which is what makes the count refresh-proof: a unique index over
    /// (Name, Meta) for that one event name means a reloaded success page cannot double-count.
    /// It identifies an order, not a person, and it is already in the buyer's own URL.
    /// </summary>
    public string? Meta { get; set; }

    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}
