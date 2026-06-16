namespace Store.Catalog.Domain;

/// <summary>
/// The buyer's right to download a specific pack. The opaque <see cref="GrantToken"/>
/// is the credential delivered by magic link — non-enumerable, fixed-time compared on
/// lookup. <see cref="ContentVersion"/> pins the version the buyer paid for, so a later
/// re-vet/republish never changes what an existing buyer receives (deliver-as-sold).
/// </summary>
public class Entitlement
{
    public long Id { get; set; }
    public long OrderId { get; set; }
    // Navigation: lets EF assign OrderId during the same SaveChanges that inserts the
    // Order, so order + entitlement are created in one atomic write.
    public Order? Order { get; set; }
    public required string PackId { get; set; }
    public string BuyerEmail { get; set; } = "";
    public required string GrantToken { get; set; }
    public EntitlementStatus Status { get; set; } = EntitlementStatus.Active;
    // The exact object-storage key sold to this buyer. Snapshotted at purchase so a later
    // republish (which writes a NEW key) never changes what this buyer downloads. This is
    // what makes deliver-as-sold actually hold; ContentVersion is the informational pin.
    public string? ContentKey { get; set; }
    public int ContentVersion { get; set; } = 1;
    public DateTime? ExpiresAt { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    public int DownloadCount { get; set; }
    public DateTime? LastDownloadedAt { get; set; }
}
