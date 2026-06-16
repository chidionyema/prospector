namespace Store.Api.Services;

/// <summary>
/// Sends the transactional magic-link email (Postmark). Returns true on success; a
/// false/throw is non-fatal to fulfilment — the entitlement already exists and the link
/// can be re-sent. When unconfigured, <see cref="IsConfigured"/> is false.
/// </summary>
public interface IEmailSender
{
    bool IsConfigured { get; }

    Task<bool> SendDownloadLinkAsync(string toEmail, string packTitle, string orderUrl);
}
