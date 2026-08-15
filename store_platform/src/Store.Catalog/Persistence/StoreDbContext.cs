using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Identity.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore;
using Store.Catalog.Domain;
using Store.Catalog.Domain.Identity;

namespace Store.Catalog.Persistence;

/// <summary>
/// One context for catalogue, orders and identity. The introduction-exchange proved the
/// alternative does not pay: its AppDbContext is an IdentityDbContext carrying 28 marketplace
/// DbSets, which is exactly why its auth layer cannot be lifted out as a unit. Here identity is
/// seven extra tables against eight existing ones, and account pages must read Orders and
/// Entitlements in the same query as the user — a second context would buy separation and cost
/// a distributed read.
/// </summary>
public class StoreDbContext(DbContextOptions<StoreDbContext> options)
    : IdentityDbContext<StoreUser, IdentityRole<Guid>, Guid>(options)
{
    public DbSet<Pack> Packs => Set<Pack>();
    public DbSet<PackPriceHistory> PackPriceHistory => Set<PackPriceHistory>();
    public DbSet<SalesAudit> SalesAudits => Set<SalesAudit>();
    public DbSet<Order> Orders => Set<Order>();
    public DbSet<Entitlement> Entitlements => Set<Entitlement>();
    public DbSet<PendingDelivery> PendingDeliveries => Set<PendingDelivery>();
    public DbSet<IdempotencyJournalEntry> IdempotencyJournal => Set<IdempotencyJournalEntry>();
    public DbSet<WebhookEvent> WebhookEvents => Set<WebhookEvent>();
    public DbSet<WaitlistSignup> WaitlistSignups => Set<WaitlistSignup>();
    public DbSet<AnalyticsEvent> AnalyticsEvents => Set<AnalyticsEvent>();

    public DbSet<UserProfile> UserProfiles => Set<UserProfile>();
    public DbSet<RefreshToken> RefreshTokens => Set<RefreshToken>();
    public DbSet<RevokedToken> RevokedTokens => Set<RevokedToken>();

    // Parameter is named `builder`, not `modelBuilder`, to match IdentityDbContext's override
    // signature (CA1725/S927). The catalogue tables moved into ConfigureCatalogTables at the
    // same time: adding the identity block pushed this method past the 60-line analyzer limit.
    protected override void OnModelCreating(ModelBuilder builder)
    {
        // Load-bearing: IdentityDbContext configures the seven Identity tables here. Skipping
        // the base call builds a model with no AspNetUsers/AspNetUserLogins at all, and the
        // failure surfaces as a confusing migration diff rather than a compile error.
        base.OnModelCreating(builder);

        ConfigureIdentity(builder);
        ConfigureCatalogTables(builder);
        ConfigureEventTables(builder);
        ConfigureDeliveryOutbox(builder);
    }

    // The outbox is configured on its own rather than folded into ConfigureCatalogTables, which
    // is already within a few lines of the 60-line analyzer limit.
    private static void ConfigureDeliveryOutbox(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<PendingDelivery>(entity =>
        {
            entity.HasKey(e => e.Id);
            // UNIQUE, and load-bearing: it is what makes enqueueing idempotent. A duplicate
            // webhook that somehow reached fulfilment twice would otherwise queue the same link
            // twice, and the database is the only thing that can see a concurrent insert.
            entity.HasIndex(e => e.EntitlementId).IsUnique();
            // The sweeper's only query is "what is still owed", so the index is on the send
            // state rather than on CreatedAt.
            entity.HasIndex(e => e.SentAt);
            entity.Property(e => e.BuyerEmail).HasMaxLength(320);   // RFC 5321 max address length
            entity.Property(e => e.LastError).HasMaxLength(500);
            entity.HasOne(e => e.Entitlement)
                  .WithMany()
                  .HasForeignKey(e => e.EntitlementId)
                  .OnDelete(DeleteBehavior.Cascade);
        });
    }

    private static void ConfigureCatalogTables(ModelBuilder modelBuilder)
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

        ConfigurePriceHistory(modelBuilder);

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
    }

    // Extracted rather than inlined into ConfigureCatalogTables for the same reason the identity
    // block was: that method is already within a few lines of the 60-line analyzer limit.
    private static void ConfigurePriceHistory(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<PackPriceHistory>(entity =>
        {
            entity.HasKey(e => e.Id);
            // The analysis query is always "what was pack P priced at over window W", so the
            // index is (PackId, CreatedAt) rather than either column alone.
            entity.HasIndex(e => new { e.PackId, e.CreatedAt });
            entity.Property(e => e.Reason).HasMaxLength(500);
            entity.Property(e => e.Actor).HasMaxLength(100);
            entity.Property(e => e.ProviderPriceId).HasMaxLength(255);
            entity.Property(e => e.RationaleRef).HasMaxLength(500);
        });
    }

    private static void ConfigureIdentity(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<StoreUser>(entity =>
        {
            // UNIQUE, unlike Identity's default EmailIndex. Account pages resolve a customer's
            // purchases by matching their verified email against Order.BuyerEmail, so two rows
            // sharing an email would each be shown the other's order history. Identity's
            // RequireUniqueEmail option enforces this in UserManager only — it is a check the
            // application performs, not a constraint the database holds, and it cannot see a
            // concurrent insert. The index is the actual guarantee.
            entity.HasIndex(e => e.NormalizedEmail).IsUnique();
            entity.Property(e => e.TosVersionAccepted).HasMaxLength(20);
            entity.Property(e => e.StripeCustomerId).HasMaxLength(255);
        });

        ConfigureUserProfile(modelBuilder);
        ConfigureTokens(modelBuilder);
    }

    private static void ConfigureUserProfile(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<UserProfile>(entity =>
        {
            entity.HasKey(e => e.Id);
            // UNIQUE: the profile is one-to-one with the account, and it is created lazily on
            // first read. Without the constraint, two concurrent reads of a profile-less account
            // both miss, both insert, and the account page then shows whichever row EF returns
            // first — a silent split-brain rather than a visible error.
            entity.HasIndex(e => e.UserId).IsUnique();
            entity.Property(e => e.FirstName).HasMaxLength(100);
            entity.Property(e => e.LastName).HasMaxLength(100);
            entity.Property(e => e.Phone).HasMaxLength(32);
            entity.Property(e => e.Bio).HasMaxLength(1000);
            entity.Property(e => e.Website).HasMaxLength(500);
            entity.Property(e => e.AvatarUrl).HasMaxLength(500);
            entity.Property(e => e.Country).HasMaxLength(2);
            entity.HasOne<StoreUser>()
                  .WithMany()
                  .HasForeignKey(e => e.UserId)
                  .OnDelete(DeleteBehavior.Cascade);
        });
    }

    private static void ConfigureTokens(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<RefreshToken>(entity =>
        {
            entity.HasKey(e => e.Id);
            entity.HasIndex(e => e.Token).IsUnique();
            // Refresh presents a token and must find its whole family to revoke on replay,
            // so both are read paths, not just the token.
            entity.HasIndex(e => e.UserId);
            entity.HasIndex(e => e.FamilyId);
            entity.Property(e => e.Token).HasMaxLength(500);
            entity.Property(e => e.AccessTokenJti).HasMaxLength(100);
            entity.HasOne<StoreUser>()
                  .WithMany()
                  .HasForeignKey(e => e.UserId)
                  .OnDelete(DeleteBehavior.Cascade);
        });

        modelBuilder.Entity<RevokedToken>(entity =>
        {
            entity.HasKey(e => e.Id);
            // Read on every authenticated request to check the deny-list, so this index is on
            // the hot path rather than a convenience.
            entity.HasIndex(e => e.Token);
            entity.HasIndex(e => e.ExpiresAt);
            // No FK to StoreUser: UserId is nullable because a token can be revoked without
            // resolving its owner, and a cascade would then delete audit-relevant rows.
        });
    }

    private static void ConfigureEventTables(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<WebhookEvent>(entity =>
        {
            entity.HasKey(e => e.Id);
            entity.HasIndex(e => new { e.Provider, e.ProviderEventId }).IsUnique();
        });

        modelBuilder.Entity<AnalyticsEvent>(entity =>
        {
            entity.HasKey(e => e.Id);
            // The only read path is the summary endpoint: counts by name over a date window.
            entity.HasIndex(e => new { e.Name, e.CreatedAt });
            // Refresh-proof purchase counting, enforced by the database rather than by a flag
            // on the buyer's device. Filtered to the one event name that carries an order id:
            // page views legitimately repeat, so a global unique index would silently drop
            // real traffic. NULL Meta stays exempt — SQLite treats NULLs as distinct.
            entity.HasIndex(e => new { e.Name, e.Meta })
                .IsUnique()
                .HasFilter("\"Name\" = 'checkout_completed' AND \"Meta\" IS NOT NULL");
            entity.Property(e => e.Name).HasMaxLength(64);
            entity.Property(e => e.Path).HasMaxLength(256);
            entity.Property(e => e.Meta).HasMaxLength(512);
        });
    }
}
