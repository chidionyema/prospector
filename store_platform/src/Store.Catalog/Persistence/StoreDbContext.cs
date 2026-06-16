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

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<Pack>(entity =>
        {
            entity.HasKey(e => e.Id);
            entity.HasIndex(e => e.IsListed);
            entity.Property(e => e.Title).HasMaxLength(200);
            entity.Property(e => e.OneLine).HasMaxLength(500);
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
