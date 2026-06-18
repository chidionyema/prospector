namespace Store.Api.Services;

/// <summary>
/// Result of applying a refund/dispute reversal (P1-1): how many entitlements were
/// revoked and how many orders were moved to a reversed status.
/// </summary>
public sealed record RevocationOutcome(int EntitlementsRevoked, int OrdersUpdated);
