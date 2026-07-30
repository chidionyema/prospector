using Microsoft.EntityFrameworkCore;
using Store.Catalog.Domain;

namespace Store.Catalog.Persistence;

public class StoreDbContext(DbContextOptions<StoreDbContext> options) : DbContext(options)
{
    public DbSet<Pack> Packs => Set<Pack>();
    public DbSet<SalesAudit> SalesAudits => Set<SalesAudit>();
    public DbSet<Order> Orders => Set<Order>();
    public DbSet<Entitlement> Entitlements => Set<Entitlement>();
    public DbSet<IdempotencyJournalEntry> IdempotencyJournal => Set<IdempotencyJournalEntry>();
    public DbSet<WebhookEvent> WebhookEvents => Set<WebhookEvent>();
    public DbSet<WaitlistSignup> WaitlistSignups => Set<WaitlistSignup>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<Pack>(entity =>
        {
            entity.HasKey(e => e.Id);
            entity.HasIndex(e => e.IsListed);
            entity.Property(e => e.Title).HasMaxLength(200);
            entity.Property(e => e.OneLine).HasMaxLength(500);
            // Facets are the browse filters, so they are read on every catalogue query.
            // Indexed individually rather than composite: filters combine in any order.
            entity.HasIndex(e => e.Sector);
            entity.HasIndex(e => e.Payer);
            entity.HasIndex(e => e.Effort);
            entity.HasIndex(e => e.Mechanism);
        });

        modelBuilder.Entity<WaitlistSignup>(entity =>
        {
            entity.HasKey(e => e.Id);
            // Not unique: the same person may legitimately ask about several different gaps,
            // and each ask carries its own consent evidence and its own demand signal.
            entity.HasIndex(e => e.Email);
            entity.HasIndex(e => e.CreatedAt);
            entity.Property(e => e.Email).HasMaxLength(320);   // RFC 5321 max address length
            entity.Property(e => e.Query).HasMaxLength(500);
        });

        modelBuilder.Entity<SalesAudit>(entity =>
        {
            entity.HasKey(e => e.Id);
            entity.HasIndex(e => new { e.PaymentProvider, e.ProviderTransactionId }).IsUnique();
        });

        modelBuilder.Entity<Order>(entity =>
        {
            entity.HasKey(e => e.Id);
            // Not unique: one transaction can yield several orders (multi-item cart).
            entity.HasIndex(e => new { e.PaymentProvider, e.ProviderTransactionId });
            entity.Property(e => e.Status).HasConversion<int>();
        });

        modelBuilder.Entity<Entitlement>(entity =>
        {
            entity.HasKey(e => e.Id);
            entity.HasIndex(e => e.GrantToken).IsUnique();
            entity.HasIndex(e => e.PackId);
            entity.Property(e => e.Status).HasConversion<int>();
        });

        modelBuilder.Entity<IdempotencyJournalEntry>(entity =>
        {
            entity.HasKey(e => e.IdempotencyKey);
            entity.HasIndex(e => e.ExpiresAt);
        });

        modelBuilder.Entity<WebhookEvent>(entity =>
        {
            entity.HasKey(e => e.Id);
            entity.HasIndex(e => new { e.Provider, e.ProviderEventId }).IsUnique();
        });
    }
}
