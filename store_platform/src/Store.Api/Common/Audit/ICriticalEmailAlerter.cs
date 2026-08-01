namespace Store.Api.Common.Audit;

/// <summary>
/// Loud-failure escalation for the ONE transactional send the store cannot afford to lose:
/// registration email verification. <see cref="ITransactionalEmailSender"/> deliberately swallows
/// provider failures so a Mailjet hiccup cannot roll back a committed registration — but that
/// silence strands the customer with an account they can never log into, because
/// <c>LoginCommand</c> refuses an unconfirmed email. The registration handler escalates here when
/// the send returns not-accepted.
///
/// Ported from the introduction-exchange, where the same seam guards the money-rail pitch relay.
/// </summary>
/// <remarks>
/// Implementations MUST be best-effort and non-throwing: a failure to escalate must never roll
/// back the committed registration. The escalation is PII-free by contract — <paramref name="context"/>
/// carries a stable label (the user id), never the recipient address.
/// </remarks>
public interface ICriticalEmailAlerter
{
    /// <param name="context">A PII-free label for the failed send, e.g. "registration email verification (user {id})".</param>
    Task RaiseSendFailureAsync(string context, CancellationToken ct = default);
}
