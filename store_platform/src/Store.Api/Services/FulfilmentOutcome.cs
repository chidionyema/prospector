using Store.Catalog.Domain;

namespace Store.Api.Services;

/// <summary>
/// Result of fulfilling a transaction. <see cref="UnfulfilledProductIds"/> is the
/// paid-without-fulfilment list (unknown product, or a pack with no deliverable
/// content) — never empty silently; every entry is an operator alert.
/// </summary>
public sealed record FulfilmentOutcome(
    bool AlreadyProcessed,
    IReadOnlyList<Entitlement> EntitlementsCreated,
    IReadOnlyList<string> Unfulfilled);
