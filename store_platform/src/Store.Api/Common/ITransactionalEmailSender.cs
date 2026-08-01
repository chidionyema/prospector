namespace Store.Api.Common;

/// <summary>
/// The seam over the transactional-email provider (Resend today). Kept provider-agnostic and
/// deliberately one-method so callers (registration, resend-verification, forgot-password) don't
/// know or care who delivers — mirrors <see cref="INotificationSender"/> and the multi-provider
/// gateway shape we may grow into later. Swap the implementation in DI to change providers; the
/// default Resend adapter no-ops to a log when unconfigured (see ResendEmailSender).
/// </summary>
/// <remarks>
/// Implementations MUST NOT throw on a provider failure: a transient outage must not roll back an
/// otherwise-successful registration. Log and return — the user can re-trigger via resend.
/// The return is the loud-failure seam (D-84), now widened to <see cref="EmailSendResult"/> (E26
/// delivery tracking): <see cref="EmailSendResult.Accepted"/> <c>true</c> means the provider accepted the
/// send (or it was intentionally no-op'd because email is unconfigured in dev/test); <c>false</c>
/// means a real provider failure. <see cref="EmailSendResult"/> converts implicitly to <c>bool</c>, so the
/// D-84 callers that wrote <c>if (!await sender.SendAsync(...))</c> are unchanged. Best-effort callers
/// ignore it; the two core-loop sends (connector pitch-relay and registration verification) check
/// <c>Accepted</c> and escalate a <c>false</c> via <see cref="ICriticalEmailAlerter"/> so a mid-money-rail
/// dead loop is never silent. The money-rail reconciliation alert (D-77) also consumes it — it records
/// <c>channel=email</c> in the audit ONLY when <c>Accepted</c>, so the audit never claims a notification
/// that did not go out. <see cref="EmailSendResult.ProviderMessageId"/> lets a delivery row correlate a
/// later provider bounce/complaint webhook back to the original send (E26 / PR3c).
/// </remarks>
public interface ITransactionalEmailSender
{
    /// <returns>An <see cref="EmailSendResult"/> whose <c>Accepted</c> is <c>true</c> if accepted by the
    /// provider or intentionally no-op'd; <c>false</c> on a real send failure.</returns>
    Task<EmailSendResult> SendAsync(string toEmail, string subject, string htmlBody, CancellationToken ct = default);
}
