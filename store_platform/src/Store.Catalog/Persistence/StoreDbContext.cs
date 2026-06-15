using Microsoft.EntityFrameworkCore;
using Store.Catalog.Domain;

namespace Store.Catalog.Persistence;

public class StoreDbContext(DbContextOptions<StoreDbContext> options) : DbContext(options)
{
    public DbSet<Pack> Packs => Set<Pack>();
    public DbSet<SalesAudit> SalesAudits => Set<SalesAudit>();

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
            entity.HasIndex(e => e.PaddleTransactionId).IsUnique();
        });
    }
}
