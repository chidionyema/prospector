namespace Store.Api.Contracts;

/// <summary>
/// Contract for POST /catalog/waitlist — the honest end of a catalogue-wide miss.
///
/// <paramref name="Consent"/> must be explicitly true. It is unticked by default in the UI and
/// rejected server-side when false, because a pre-ticked or inferred consent box is not consent
/// under UK GDPR. <paramref name="ConsentText"/> is the exact sentence the person was shown; the
/// server hashes it rather than trusting a client-supplied hash, so the stored evidence is of
/// what was actually rendered.
/// </summary>
public record WaitlistRequest(
    string Email,
    bool Consent,
    string ConsentText,
    string? ConsentVersion = null,
    string? Query = null,
    string? Source = null
);
