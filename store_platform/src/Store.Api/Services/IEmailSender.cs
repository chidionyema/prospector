namespace Store.Api.Services;

/// <summary>
/// Sends the transactional magic-link email (Mailjet). Returns true on success; false is
/// non-fatal to fulfilment — the entitlement already exists and the link can be re-sent.
/// When unconfigured, <see cref="IsConfigured"/> is false. Implementations must not throw:
/// the caller runs inside the Stripe webhook, after the money is captured.
/// </summary>
public interface IEmailSender
{
    bool IsConfigured { get; }

    Task<bool> SendDownloadLinkAsync(string toEmail, string packTitle, string orderUrl);
}
