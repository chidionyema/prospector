namespace Store.Catalog.Domain.Identity;

/// <summary>
/// Base class for Guid-keyed identity entities with audit metadata. Ported from the
/// introduction-exchange (Tie.SharedKernel/Persistence/AuditableEntity.cs).
///
/// The original carried a PostgreSQL <c>xmin</c> optimistic-concurrency token, configured
/// per entity via <c>UseXminAsConcurrencyToken()</c>. That is deliberately NOT ported:
/// <c>xmin</c> is a Postgres system column and does not exist in SQLite, so the mapping
/// would fail at model-build time. A stored byte[] rowversion is not a substitute either —
/// SQLite would never auto-increment it, so it would compile, migrate, and silently protect
/// nothing. Refresh-token rotation is instead guarded by the single-writer property of this
/// deployment (deploy/fly/api.fly.toml pins the API to exactly one machine).
/// </summary>
public abstract class AuditableEntity
{
    protected AuditableEntity()
    {
        Id = Guid.NewGuid();
        CreatedAt = DateTime.UtcNow;
    }

    public Guid Id { get; set; }
    public DateTime CreatedAt { get; set; }

    /// <summary>
    /// Originating IP, recorded on refresh tokens so the account page can list active sessions as
    /// "signed in from ...". Not decoration: it is the only way a customer can recognise a session
    /// they did not start and revoke it. <c>ModifiedFromIp</c> from the source repo is deliberately
    /// not ported — nothing reads it here.
    /// </summary>
    public string? CreatedFromIp { get; set; }

    public string? CreatedBy { get; set; }
    public string? LastModifiedBy { get; set; }
    public DateTime? LastModifiedDate { get; set; }
}
