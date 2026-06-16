using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using Store.Api.Services;
using Store.Catalog.Domain;
using Store.Catalog.Persistence;

namespace Store.Tests.Fulfilment;

/// <summary>
/// Exercises the money-critical atomic core on a real (in-memory) SQLite database so the
/// unique SalesAudit index actually enforces idempotency — the EF InMemory provider would
/// silently allow duplicates and give false confidence.
/// </summary>
public sealed class FulfilmentServiceTests : IDisposable
{
    private readonly SqliteConnection _connection;
    private readonly DbContextOptions<StoreDbContext> _options;

    public FulfilmentServiceTests()
    {
        _connection = new SqliteConnection("Data Source=:memory:");
        _connection.Open();
        _options = new DbContextOptionsBuilder<StoreDbContext>()
            .UseSqlite(_connection)
            .Options;
        using var ctx = new StoreDbContext(_options);
        ctx.Database.EnsureCreated();
    }

    [Fact]
    public async Task FulfilAsync_KnownPackWithContent_CreatesPinnedEntitlement()
    {
        await SeedPackAsync("pack-1", "prod-1", "content/pack-1.zip", version: 2)
            ;

        var outcome = await RunAsync(Txn("txn-1", new PurchasedItem("prod-1", 3000)))
            ;

        Assert.False(outcome.AlreadyProcessed);
        Assert.Single(outcome.EntitlementsCreated);
        Assert.Empty(outcome.Unfulfilled);

        var ent = outcome.EntitlementsCreated[0];
        Assert.Equal("pack-1", ent.PackId);
        Assert.Equal(2, ent.ContentVersion); // pinned to the version sold (deliver-as-sold)
        Assert.Equal("content/pack-1.zip", ent.ContentKey); // snapshot of exactly what was sold
        Assert.False(string.IsNullOrEmpty(ent.GrantToken));

        using var verify = NewContext();
        Assert.Equal(1, await verify.SalesAudits.CountAsync());
        Assert.Equal(1, await verify.Orders.CountAsync());
        Assert.Equal(1, await verify.Entitlements.CountAsync());
    }

    [Fact]
    public async Task FulfilAsync_DuplicateTransaction_IsIdempotent()
    {
        await SeedPackAsync("pack-1", "prod-1", "k.zip");
        await RunAsync(Txn("txn-1", new PurchasedItem("prod-1", 3000)));

        var outcome = await RunAsync(Txn("txn-1", new PurchasedItem("prod-1", 3000)))
            ;

        Assert.True(outcome.AlreadyProcessed);
        using var verify = NewContext();
        Assert.Equal(1, await verify.SalesAudits.CountAsync());
        Assert.Equal(1, await verify.Entitlements.CountAsync());
    }

    [Fact]
    public async Task FulfilAsync_UnknownProduct_RecordsOrderButNoEntitlement()
    {
        var outcome = await RunAsync(Txn("txn-1", new PurchasedItem("ghost", 3000)))
            ;

        Assert.Empty(outcome.EntitlementsCreated);
        Assert.Contains("ghost", outcome.Unfulfilled);

        using var verify = NewContext();
        Assert.Equal(1, await verify.Orders.CountAsync());
        Assert.Equal(0, await verify.Entitlements.CountAsync());
    }

    [Fact]
    public async Task FulfilAsync_PackWithoutContent_IsUnfulfilled()
    {
        await SeedPackAsync("pack-1", "prod-1", contentKey: null);

        var outcome = await RunAsync(Txn("txn-1", new PurchasedItem("prod-1", 3000)))
            ;

        Assert.Empty(outcome.EntitlementsCreated);
        Assert.Contains("prod-1", outcome.Unfulfilled);
    }

    [Fact]
    public async Task FulfilAsync_MultipleItems_CreatesEntitlementPerDeliverable()
    {
        await SeedPackAsync("pack-1", "prod-1", "k1.zip");
        await SeedPackAsync("pack-2", "prod-2", "k2.zip");

        var outcome = await RunAsync(Txn(
            "txn-1",
            new PurchasedItem("prod-1", 1500),
            new PurchasedItem("prod-2", 1500)));

        Assert.Equal(2, outcome.EntitlementsCreated.Count);
        Assert.Empty(outcome.Unfulfilled);
        Assert.NotEqual(
            outcome.EntitlementsCreated[0].GrantToken,
            outcome.EntitlementsCreated[1].GrantToken);
    }

    [Fact]
    public async Task FulfilAsync_NoItems_RecordsOrphanOrderAndFlags()
    {
        var outcome = await RunAsync(Txn("txn-1"));

        Assert.Empty(outcome.EntitlementsCreated);
        Assert.Contains("(no items)", outcome.Unfulfilled);

        using var verify = NewContext();
        var order = await verify.Orders.FirstAsync();
        Assert.Null(order.PackId);
    }

    private async Task<FulfilmentOutcome> RunAsync(PaymentTransaction txn)
    {
        using var ctx = NewContext();
        var svc = new FulfilmentService(ctx, new TokenGenerator());
        return await svc.FulfilAsync(txn);
    }

    private async Task SeedPackAsync(string id, string productId, string? contentKey, int version = 1)
    {
        using var ctx = NewContext();
        ctx.Packs.Add(new Pack
        {
            Id = id,
            Title = id,
            OneLine = "x",
            DossierRef = "d",
            ProviderProductId = productId,
            ContentKey = contentKey,
            ContentVersion = version,
        });
        await ctx.SaveChangesAsync();
    }

    private static PaymentTransaction Txn(string id, params PurchasedItem[] items) =>
        new("paddle", id, "buyer@example.com", "GBP", "GB", 3000, new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc), items);

    private StoreDbContext NewContext() => new(_options);

    public void Dispose()
    {
        _connection.Dispose();
        GC.SuppressFinalize(this);
    }
}
