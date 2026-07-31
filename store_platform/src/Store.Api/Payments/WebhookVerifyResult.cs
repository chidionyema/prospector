using Store.Api.Services;

namespace Store.Api.Payments;

// Reversal is set (and Transaction null) when the event is a refund/dispute that must
// REVOKE a prior entitlement rather than grant one. See P1-1.
public sealed record WebhookVerifyResult(
    bool Verified,
    PaymentTransaction? Transaction,
    string? Reason,
    bool Ignored = false,
    PaymentReversal? Reversal = null);
