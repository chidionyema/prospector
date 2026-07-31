namespace Store.Catalog.Domain;

/// <summary>
/// One anonymous storefront interaction: a page view, a hero CTA click, a completed checkout.
///
/// This table exists to answer one question — "does the storefront convert, and at what
/// volume?" — because until it can be answered, no copy test is measurable. It is a tally,
/// not a profile: no IP, no user agent, no cookie, no email. SessionId is a random value
/// minted client-side into sessionStorage, so it dies with the browser tab session and links
/// nothing across visits. That is deliberate: the moment this table can identify a person it
/// stops being a tally and starts being personal data with consent obligations.
/// </summary>
public class AnalyticsEvent
{
    public long Id { get; set; }

    /// <summary>Event name from the server-side allowlist (e.g. "page_view"). Never free text.</summary>
    public required string Name { get; set; }

    /// <summary>Pathname only (e.g. "/pack/abc") — never query strings, which can carry tokens.</summary>
    public string? Path { get; set; }

    /// <summary>Random per-browser-tab-session id; dies with the tab. For funnel dedup only.</summary>
    public string? SessionId { get; set; }

    /// <summary>Small event-specific detail, e.g. the checkout session id for refresh dedup.</summary>
    public string? Meta { get; set; }

    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}
