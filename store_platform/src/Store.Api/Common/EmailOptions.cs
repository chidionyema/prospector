namespace Store.Api.Common;

/// <summary>
/// Transactional-email settings. Bound from the "Email" config section. These drive the
/// verification email that unlocks login + Stripe KYC onboarding, and the password-reset email.
/// </summary>
public sealed class EmailOptions
{
    public const string SectionName = "Email";

    // Enabled / ApiKey / FromAddress / FromName are deliberately NOT ported. The store already
    // configures its sender under "Mailjet" (ApiKey, ApiSecret, FromEmail — see
    // Services/MailjetEmailSender.cs), and MailjetEmailSender.IsConfigured is already the
    // "credentials present?" switch that makes an unconfigured environment log instead of send.
    // Duplicating those four keys here would create a second place to configure email and a state
    // where the two disagree — Email__Enabled=true with no Mailjet secret, or mail going out from
    // a from-address that only one of the two knows about. One source, one failure mode.

    /// <summary>
    /// Public web origin used to build click-through links in emails (e.g. the verify-email and
    /// reset-password pages). Why it matters: the link host must match the deployed frontend
    /// (dev/staging/prod differ), so it has to be environment-configurable. Trailing slash is
    /// tolerated — link builders trim it.
    /// </summary>
    public string WebBaseUrl { get; set; } = "http://localhost:3000";
}
