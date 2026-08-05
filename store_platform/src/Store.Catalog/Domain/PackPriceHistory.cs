namespace Store.Catalog.Domain;

/// <summary>
/// One price change, recorded at the moment it is applied.
///
/// This is not bookkeeping-for-its-own-sake, and it is not the same thing as the analytics
/// events. It exists because a price is only meaningful alongside the window it was live in:
/// a conversion tells you nothing unless you can say what the buyer was shown, and the pack
/// row only ever holds the CURRENT price. Without this table, the moment a price moves, every
/// prior sale becomes unattributable and any pricing experiment is unanalysable after the fact
/// — including experiments already finished. The row must therefore be written on the same
/// transaction as the change, not reconstructed later from logs.
///
/// It is also the rollback record: "restore every price to what it was on date X" is a query
/// against this table rather than an archaeology exercise across Stripe and the audit log.
///
/// Reason and Actor are required by the endpoint for the same purpose DelistReason serves on
/// Pack — a price that moved with no stated cause is indistinguishable from a bug, and the next
/// person to look will move it back.
/// </summary>
public class PackPriceHistory
{
    public long Id { get; set; }

    public required string PackId { get; set; }

    /// <summary>The pack's PricePence immediately before this change.</summary>
    public long FromPence { get; set; }

    /// <summary>The pack's PricePence immediately after.</summary>
    public long ToPence { get; set; }

    /// <summary>
    /// The fulfilment floor left in place by this change. Recorded because it is derived state
    /// that the pack row overwrites on the next change: reading a historical sale's legitimacy
    /// back needs the floor as it stood then, not as it stands now.
    /// </summary>
    public long MinBillablePence { get; set; }

    /// <summary>
    /// The provider Price object new sessions mint from after this change. Stripe Price objects
    /// are immutable, so a change points at a NEW id and the old one is deactivated rather than
    /// deleted — historical sessions and receipts must stay resolvable.
    /// </summary>
    public string? ProviderPriceId { get; set; }

    /// <summary>Why, in one line. Required by the endpoint.</summary>
    public required string Reason { get; set; }

    /// <summary>Who or what applied it (e.g. "price-engine", "founder"). Required.</summary>
    public required string Actor { get; set; }

    /// <summary>
    /// Optional pointer to the engine-side rationale record holding the full derivation and its
    /// cited comparables. The price is the claim; that file is the receipt.
    /// </summary>
    public string? RationaleRef { get; set; }

    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
}
