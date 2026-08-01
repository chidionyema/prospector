using Microsoft.Extensions.Logging;

namespace Store.Api.Common.Audit;

/// <summary>
/// The beta implementation: escalate to the log at Critical, which is where the store's alerting
/// already watches. Deliberately not a second email — the failure being reported IS that email
/// sending is broken, so a mail-based escalation is the one channel known to be down.
/// </summary>
public sealed class LoggingCriticalEmailAlerter(ILogger<LoggingCriticalEmailAlerter> logger)
    : ICriticalEmailAlerter
{
    public Task RaiseSendFailureAsync(string context, CancellationToken ct = default)
    {
        logger.LogCritical(
            "Transactional email send FAILED and was not delivered: {Context}. " +
            "The customer cannot verify their email and therefore cannot log in.", context);
        return Task.CompletedTask;
    }
}
