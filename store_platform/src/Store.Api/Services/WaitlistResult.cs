using Store.Catalog.Domain;

namespace Store.Api.Services;

/// <summary>
/// The outcome of a waitlist signup attempt: either the stored row, or a reason the caller can
/// turn straight into a 400 that names the offending field.
///
/// Modelled as a result rather than an exception because a missing tick in a consent box is an
/// ordinary, expected answer from a user — not an exceptional condition — and the endpoint
/// should not have to catch to handle the common case.
/// </summary>
public sealed record WaitlistResult(WaitlistSignup? Signup, string? Error)
{
    public bool Succeeded => Signup is not null;

    public static WaitlistResult Rejected(string error) => new(null, error);

    public static WaitlistResult Accepted(WaitlistSignup signup) => new(signup, null);
}
