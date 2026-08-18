using Microsoft.Extensions.DependencyInjection;
using Store.Catalog.Domain;
using Store.Catalog.Persistence;

namespace Store.Tests.Endpoints;

/// <summary>
/// Seeds one shop's worth of history once, so the aggregate assertions in
/// <see cref="OpsEndpointsTests"/> have a fixed denominator. Each <see cref="StoreApiFactory"/>
/// owns a throwaway SQLite file, so this data cannot leak into another test class.
///
/// Nothing here writes. The resend endpoint mutates rows, so its tests seed their own database
/// (<see cref="OpsResendTests"/>) rather than moving the counts this fixture pins.
/// </summary>
public sealed class OpsSeedFixture : IAsyncLifetime
{
    public StoreApiFactory Factory { get; } = new();

    /// <summary>
    /// The prefix every seeded grant token carries. No operator response may ever contain it.
    /// It is a prefix rather than the whole token because <c>Entitlements.GrantToken</c> is
    /// unique in the schema: seeding one literal on three entitlements fails the insert, which is
    /// correct — a grant token that repeats would let one buyer download another's pack.
    /// </summary>
    public const string SecretGrantToken = "grant_token_that_must_never_be_returned";

    public long CartOrderId { get; private set; }
    public long SoloOrderId { get; private set; }

    public async Task InitializeAsync()
    {
        using var scope = Factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<StoreDbContext>();

        var today = DateTime.UtcNow;
        var fiveDaysAgo = today.AddDays(-5);

        db.Packs.Add(NewPack("pack-alpha", "Alpha pack"));
        db.Packs.Add(NewPack("pack-beta", "Beta pack"));

        // 1. A single-item GBP sale that was delivered and downloaded.
        db.SalesAudits.Add(NewAudit("txn_solo", "prod_alpha", 4900, "gbp", today));
        var solo = NewOrder("txn_solo", "buyer.one@example.com", "pack-alpha", 4900, "gbp", today);
        db.Orders.Add(solo);
        var soloEnt = NewEntitlement(solo, "pack-alpha", downloads: 2);
        db.Entitlements.Add(soloEnt);
        db.PendingDeliveries.Add(NewDelivery(soloEnt, "pack-alpha", sentAt: today, attempts: 1));

        // 2. A two-item GBP cart bought with a discount. This row is the whole point of the
        //    revenue rule: the transaction took 6500, while the two Order rows split 7000
        //    between them. Anything that computes revenue by summing Orders reports 500 the
        //    shop never received.
        db.SalesAudits.Add(NewAudit("txn_cart", "prod_cart", 6500, "gbp", today));
        var cartA = NewOrder("txn_cart", "buyer.two@example.com", "pack-alpha", 4900, "gbp", today);
        var cartB = NewOrder("txn_cart", "buyer.two@example.com", "pack-beta", 2100, "gbp", today);
        db.Orders.Add(cartA);
        db.Orders.Add(cartB);
        var cartEntA = NewEntitlement(cartA, "pack-alpha");
        var cartEntB = NewEntitlement(cartB, "pack-beta");
        db.Entitlements.Add(cartEntA);
        db.Entitlements.Add(cartEntB);
        // One link that has been tried and keeps failing, one that has never been tried.
        db.PendingDeliveries.Add(NewDelivery(cartEntA, "pack-alpha", sentAt: null, attempts: 3,
            lastError: "mailjet returned 500"));
        db.PendingDeliveries.Add(NewDelivery(cartEntB, "pack-beta", sentAt: null, attempts: 0));

        SeedUsdAndRefund(db, today, fiveDaysAgo);

        await db.SaveChangesAsync();

        SoloOrderId = solo.Id;
        CartOrderId = cartA.Id;
    }

    private static void SeedUsdAndRefund(StoreDbContext db, DateTime today, DateTime fiveDaysAgo)
    {
        // 3. A USD sale. It must never be added to the GBP figures.
        db.SalesAudits.Add(NewAudit("txn_usd", "prod_beta", 6500, "usd", today));
        db.Orders.Add(NewOrder("txn_usd", "buyer.us@example.com", "pack-beta", 6500, "usd", today,
            country: "US"));

        // 4. An older, refunded GBP sale, inside the 30-day window but not today. Its entitlement
        //    is Revoked, which is what FulfilmentService.RevokeAsync:190 does to every reversal.
        db.SalesAudits.Add(NewAudit("txn_refund", "prod_alpha", 4900, "gbp", fiveDaysAgo));
        var refundOrder = NewOrder("txn_refund", "buyer.three@example.com", "pack-alpha", 4900,
            "gbp", fiveDaysAgo, status: OrderStatus.Refunded);
        db.Orders.Add(refundOrder);
        var refundEnt = NewEntitlement(refundOrder, "pack-alpha");
        refundEnt.Status = EntitlementStatus.Revoked;
        db.Entitlements.Add(refundEnt);

        // 5. A delivery the drain gave up on: ten attempts, never sent, nothing will retry it.
        //    It hangs off the REFUNDED order rather than the solo one, because
        //    PendingDeliveries.EntitlementId is UNIQUE (StoreDbContext.cs:61) — one entitlement
        //    may hold exactly one outbox row. Seeded last, so its row id (4) differs from its
        //    order id (5): a screen or an endpoint that treats a delivery id as an order id is
        //    caught rather than passing by coincidence on ids that happen to line up.
        db.PendingDeliveries.Add(NewDelivery(refundEnt, "pack-alpha", sentAt: null, attempts: 10,
            lastError: "mailjet returned 500 (final attempt)"));
    }

    public Task DisposeAsync()
    {
        Factory.Dispose();
        return Task.CompletedTask;
    }

    private static Pack NewPack(string id, string title) => new()
    {
        Id = id,
        Title = title,
        OneLine = $"{title} one-liner",
        DossierRef = $"dossier-{id}",
        PricePence = 4900,
        IsListed = true,
    };

    private static SalesAudit NewAudit(string txn, string product, long amount, string currency,
        DateTime occurredAt) => new()
    {
        ProviderTransactionId = txn,
        ProviderProductId = product,
        AmountPence = amount,
        Currency = currency,
        Country = "GB",
        OccurredAt = occurredAt,
    };

    private static Order NewOrder(string txn, string email, string packId, long amount,
        string currency, DateTime createdAt, string country = "GB",
        OrderStatus status = OrderStatus.Paid) => new()
    {
        ProviderTransactionId = txn,
        BuyerEmail = email,
        PackId = packId,
        AmountPence = amount,
        Currency = currency,
        Country = country,
        Status = status,
        CreatedAt = createdAt,
    };

    private static Entitlement NewEntitlement(Order order, string packId, int downloads = 0) => new()
    {
        Order = order,
        PackId = packId,
        BuyerEmail = order.BuyerEmail,
        GrantToken = $"{SecretGrantToken}_{packId}_{order.BuyerEmail}",
        ContentKey = $"packs/{packId}/content.zip",
        DownloadCount = downloads,
        LastDownloadedAt = downloads > 0 ? DateTime.UtcNow : null,
    };

    private static PendingDelivery NewDelivery(Entitlement entitlement, string packId,
        DateTime? sentAt, int attempts, string? lastError = null) => new()
    {
        Entitlement = entitlement,
        PackId = packId,
        BuyerEmail = entitlement.BuyerEmail,
        GrantToken = entitlement.GrantToken,
        SentAt = sentAt,
        Attempts = attempts,
        LastError = lastError,
    };
}
