using Microsoft.Extensions.Logging;

namespace Store.Api.Common.Audit;

/// <summary>Canonical audit-event action names.</summary>
public static class AuditActions
{
    public const string Register = "auth.register";
    public const string RegisterFailed = "auth.register.failed";
    public const string Login = "auth.login";
    public const string LoginFailed = "auth.login.failed";
    public const string Logout = "auth.logout";
    public const string AccountLockout = "auth.account.lockout";
    public const string TokenRefresh = "auth.token.refresh";
    public const string PasswordChange = "auth.password.change";
    public const string PasswordReset = "auth.password.reset";
    public const string EmailVerify = "auth.email.verify";
    public const string EmailVerifyResend = "auth.email.verify.resend";
    public const string ProfileUpdate = "profile.update";
    public const string PayoutReadyCleared = "onboarding.payout_ready.cleared"; // E02-015 — a connector's KYC cleared and the acceptance gate opened

    // E14 — admin money-safety surface (WR-002).
    public const string KillSwitchEngage = "admin.killswitch.engage";
    public const string KillSwitchDisengage = "admin.killswitch.disengage";
    public const string ReconciliationRun = "admin.reconciliation.run";
    public const string SettlementSweepRun = "admin.settlement.sweep.run"; // WR-028 — on-demand settlement drive (D-67 manual control + smoke driver)
    public const string AdminLedgerRead = "admin.ledger.read";            // WR-028 — privileged raw-ledger read (smoke Stripe-Transfer assertion)
    public const string ReconciliationAlertSent = "admin.reconciliation.alert.sent"; // WR-029 — a human was notified of a reconciliation state-change (counts only, no detail)
    public const string CoreLoopEmailFailed = "email.coreloop.failed"; // D-84 — a core-loop transactional send (pitch-relay / verification) failed and was escalated (PII-free)
    public const string EmailBounceReceived = "email.bounce.received"; // E26-004 — a Resend bounce/complaint webhook marked a tracked delivery undeliverable (delivery id only, no recipient)
    public const string ProblemReportFiled = "report.filed";           // E26-006 — a user filed a "report a problem" intake row (support queue)
    public const string ProblemReportClosed = "report.closed";         // E26-006 — an operator triaged/closed a problem report

    // Additional actions from spec F1 if needed
    public const string DisputeResolve = "admin.dispute.resolve";

    // Founder preview — reading a pack's contents without a purchase. Both outcomes are named:
    // an allowlist fence that only records its successes cannot show that anyone tried.
    public const string FounderPreview = "founder.preview";
    public const string FounderPreviewDenied = "founder.preview.denied";
}

/// <summary>A structured audit event. Mirrors haworks BuildingBlocks/Audit.</summary>
public sealed class AuditEvent
{
    public string Action { get; init; } = string.Empty;
    public string UserId { get; init; } = string.Empty;
    public string? UserRole { get; init; }
    public string Resource { get; init; } = string.Empty;
    public Guid? TargetId { get; init; }
    public bool IsSuccess { get; init; }
    public string? BeforeStateJson { get; init; }
    public string? AfterStateJson { get; init; }
    public string? Details { get; init; } // maps to Reason in AuditEntry
    public string? IpAddress { get; init; }
    public string? UserAgent { get; init; }
    public string? CorrelationId { get; init; }
}

/// <summary>Append-only audit trail. Lean default writes structured logs; can be backed by a table later.</summary>
public interface IAuditLogger
{
    Task LogAsync(AuditEvent auditEvent, CancellationToken ct = default);
}

/// <summary>
/// Structured-log audit sink. A production deployment can swap this for a
/// Postgres-backed implementation without touching call sites.
/// </summary>
public sealed class LoggingAuditLogger : IAuditLogger
{
    private readonly ILogger<LoggingAuditLogger> _logger;

    public LoggingAuditLogger(ILogger<LoggingAuditLogger> logger) => _logger = logger;

    public Task LogAsync(AuditEvent auditEvent, CancellationToken ct = default)
    {
        _logger.LogInformation(
            "AUDIT {Action} success={Success} user={UserId} role={UserRole} resource={Resource} target={TargetId} ip={Ip} correlation={CorrelationId} details={Details}",
            auditEvent.Action, auditEvent.IsSuccess, auditEvent.UserId, auditEvent.UserRole,
            auditEvent.Resource, auditEvent.TargetId, auditEvent.IpAddress, auditEvent.CorrelationId, auditEvent.Details);
        return Task.CompletedTask;
    }
}
