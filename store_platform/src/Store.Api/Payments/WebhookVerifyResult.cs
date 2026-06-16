using Store.Api.Services;

namespace Store.Api.Payments;

public sealed record WebhookVerifyResult(bool Verified, PaymentTransaction? Transaction, string? Reason, bool Ignored = false);
