namespace Store.Catalog.Domain;

/// <summary>
/// The delivery outbox: "this buyer is owed a download link", written in the SAME
/// <c>SaveChangesAsync</c> as the <see cref="Entitlement"/> it belongs to.
///
/// This row exists because the entitlement was durable and the email was not. The email used to
/// be dispatched inline in the webhook handler, AFTER the fulfilment commit and outside it, so a
/// restart, a crash or a transient Mailjet failure between the commit and the send lost the link
/// permanently: Stripe's retry hits the dedup short-circuit, returns ALREADY_PROCESSED, and never
/// reaches the send at all. Every API deploy is exactly that window -- the app runs a single
/// machine on SQLite (see deploy/fly/api.fly.toml), so a deploy is a SIGTERM with no drain.
///
/// The invariant this buys: the obligation to deliver is as durable as the entitlement, because
/// it is committed by the same transaction. A sweeper (Store.Api DeliveryDrain) is the only
/// sender, so redelivery is retry rather than a lucky re-entry into a code path.
/// <see cref="SentAt"/> is the receipt; a crash mid-drain costs at worst a duplicate email, which
/// is the correct side of that trade for a link the buyer has already paid for.
/// </summary>
public class PendingDelivery
{
    public long Id { get; set; }

    public long EntitlementId { get; set; }

    /// <summary>
    /// Navigation, not a manually-assigned id. <see cref="EntitlementId"/> does not exist until
    /// the insert, so the outbox row can only be enqueued atomically with its entitlement by
    /// letting EF fix the key up during the same SaveChanges -- the same reason
    /// <see cref="Entitlement.Order"/> is a navigation.
    /// </summary>
    public Entitlement? Entitlement { get; set; }

    public required string PackId { get; set; }

    public string BuyerEmail { get; set; } = "";

    /// <summary>
    /// Snapshotted rather than read back through the entitlement: the link is what is owed, and
    /// the sweeper must be able to address it without depending on the entitlement's later state.
    /// </summary>
    public required string GrantToken { get; set; }

    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    /// <summary>Null until the link has actually gone out. The only definition of "delivered".</summary>
    public DateTime? SentAt { get; set; }

    public int Attempts { get; set; }

    public string? LastError { get; set; }
}
