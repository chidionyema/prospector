namespace Store.Api.Common;

/// <summary>
/// Outcome of an <see cref="Interfaces.ITransactionalEmailSender"/> send (E26 delivery tracking). Widens the older
/// D-84 <c>bool</c> "accepted?" signal so callers that persist a delivery row can correlate a later
/// provider webhook (bounce/complaint/delivered) back to the send via <see cref="ProviderMessageId"/>.
/// </summary>
/// <param name="Accepted">
/// <c>true</c> when the provider accepted the send OR it was intentionally no-op'd because email is
/// unconfigured (dev/test/CI). <c>false</c> only on a real provider rejection/exception. This is the
/// SAME meaning the D-84 loud-failure seam had as a bare <c>bool</c> — see <see cref="op_Implicit"/>.
/// </param>
/// <param name="ProviderMessageId">
/// The provider's message id (Resend <c>id</c>) when accepted and known; <c>null</c> on a no-op send
/// (unconfigured) or a failure. The bounce webhook (PR3c) keys off this to mark the row bounced/complained.
/// </param>
/// <param name="Error">A short, non-PII failure detail for the audit/ops trail; <c>null</c> on success.</param>
public sealed record EmailSendResult(bool Accepted, string? ProviderMessageId, string? Error)
{
    /// <summary>A successful no-op (email intentionally not configured): accepted, no provider id, no error.
    /// Preserves the D-84 contract that an unconfigured sender never trips the core-loop loud-failure path.</summary>
    public static readonly EmailSendResult NoOp = new(true, null, null);

    /// <summary>Source-compat shim for the D-84 callers that consumed a bare <c>bool</c> ("was it accepted?"):
    /// <c>if (!await sender.SendAsync(...))</c> keeps compiling and means exactly what it did before.</summary>
    public static implicit operator bool(EmailSendResult result) => result.Accepted;
}
