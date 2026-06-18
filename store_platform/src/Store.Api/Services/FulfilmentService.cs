using Microsoft.EntityFrameworkCore;
using Store.Catalog.Domain;
using Store.Catalog.Persistence;

namespace Store.Api.Services;

/// <summary>
/// Turns a completed payment into durable fulfilment: a financial SalesAudit row, an
/// Order per purchased item, and an Entitlement per deliverable pack — all in one atomic
/// write. Idempotent on the unique SalesAudit transaction id, even under concurrent
/// duplicate webhooks. Never drops a paid sale: unknown/undeliverable items are recorded
/// as Orders and reported as unfulfilled for operator follow-up.
/// </summary>
public sealed class FulfilmentService(StoreDbContext db, ITokenGenerator tokens)
{
    public async Task<FulfilmentOutcome> FulfilAsync(PaymentTransaction txn)
    {
        ArgumentNullException.ThrowIfNull(txn);

        if (await TransactionAlreadyRecordedAsync(txn.Provider, txn.TransactionId).ConfigureAwait(false))
        {
            return new FulfilmentOutcome(true, [], []);
        }

        db.SalesAudits.Add(BuildAudit(txn));

        var created = new List<Entitlement>();
        var unfulfilled = new List<string>();

        if (txn.Items.Count == 0)
        {
            // Paid but nothing to deliver. Record the order so the money is never lost.
            db.Orders.Add(NewOrder(txn, packId: null, txn.TotalAmountPence));
            unfulfilled.Add("(no items)");
        }

        foreach (var item in txn.Items)
        {
            await FulfilItemAsync(txn, item, created, unfulfilled).ConfigureAwait(false);
        }

        return await CommitAsync(txn, created, unfulfilled).ConfigureAwait(false);
    }

    private async Task FulfilItemAsync(
        PaymentTransaction txn, PurchasedItem item, List<Entitlement> created, List<string> unfulfilled)
    {
        // Resolve the deliverable pack from the identifier carried on the transaction.
        // Stripe stamps the catalog pack id into checkout metadata (P0-1); Paddle carries
        // the provider product id on its line items. Match either, scoped to the provider.
        var pack = item.ProductId is null
            ? null
            : await db.Packs.FirstOrDefaultAsync(p =>
                (p.Id == item.ProductId || p.ProviderProductId == item.ProductId)
                && p.PaymentProvider == txn.Provider).ConfigureAwait(false);

        var order = NewOrder(txn, pack?.Id, item.AmountPence);
        db.Orders.Add(order);

        if (pack is null || string.IsNullOrEmpty(pack.ContentKey))
        {
            // Unknown product, or a listed pack with no deliverable content (should be
            // impossible given list-only-after-upload). Record, alert, never drop.
            unfulfilled.Add(item.ProductId ?? "(null product)");
            return;
        }

        var entitlement = new Entitlement
        {
            Order = order,
            PackId = pack.Id,
            BuyerEmail = txn.BuyerEmail,
            GrantToken = tokens.NewToken(),
            Status = EntitlementStatus.Active,
            ContentKey = pack.ContentKey, // snapshot exactly what was sold (deliver-as-sold)
            ContentVersion = pack.ContentVersion,
            ExpiresAt = null,
        };
        db.Entitlements.Add(entitlement);
        created.Add(entitlement);
    }

    private async Task<FulfilmentOutcome> CommitAsync(
        PaymentTransaction txn, IReadOnlyList<Entitlement> created, IReadOnlyList<string> unfulfilled)
    {
        try
        {
            await db.SaveChangesAsync().ConfigureAwait(false);
        }
        catch (DbUpdateException)
        {
            // A concurrent duplicate webhook may have won the race to the unique
            // SalesAudit row. If the transaction is now recorded, treat as already
            // processed; otherwise it is a real failure — rethrow so the caller returns
            // a non-2xx and the provider retries.
            db.ChangeTracker.Clear();
            if (await TransactionAlreadyRecordedAsync(txn.Provider, txn.TransactionId).ConfigureAwait(false))
            {
                return new FulfilmentOutcome(true, [], []);
            }

            throw;
        }

        return new FulfilmentOutcome(false, created, unfulfilled);
    }

    /// <summary>
    /// P1-1 — apply a refund/dispute reversal: revoke every Active entitlement granted for
    /// the original payment and move its orders to a reversed status, so a refunded/disputed
    /// buyer can no longer download. Idempotent: re-applying finds nothing Active and is a
    /// no-op. Matches the original payment by provider + transaction id.
    /// </summary>
    public async Task<RevocationOutcome> RevokeAsync(Store.Api.Payments.PaymentReversal reversal)
    {
        ArgumentNullException.ThrowIfNull(reversal);

        var entitlements = await db.Entitlements
            .Where(e => e.Order!.ProviderTransactionId == reversal.OriginalTransactionId
                        && e.Order.PaymentProvider == reversal.Provider
                        && e.Status == EntitlementStatus.Active)
            .ToListAsync()
            .ConfigureAwait(false);

        foreach (var ent in entitlements)
        {
            ent.Status = EntitlementStatus.Revoked;
        }

        var newOrderStatus = string.Equals(reversal.Kind, "dispute", StringComparison.Ordinal)
            ? OrderStatus.Disputed : OrderStatus.Refunded;
        var orders = await db.Orders
            .Where(o => o.ProviderTransactionId == reversal.OriginalTransactionId
                        && o.PaymentProvider == reversal.Provider)
            .ToListAsync()
            .ConfigureAwait(false);
        foreach (var order in orders)
        {
            order.Status = newOrderStatus;
        }

        await db.SaveChangesAsync().ConfigureAwait(false);
        return new RevocationOutcome(entitlements.Count, orders.Count);
    }

    private Task<bool> TransactionAlreadyRecordedAsync(string provider, string transactionId) =>
        db.SalesAudits.AnyAsync(s => s.PaymentProvider == provider && s.ProviderTransactionId == transactionId);

    private static SalesAudit BuildAudit(PaymentTransaction txn) => new()
    {
        PaymentProvider = txn.Provider,
        ProviderTransactionId = txn.TransactionId,
        ProviderProductId = txn.Items.Count > 0 ? txn.Items[0].ProductId ?? "" : "",
        AmountPence = txn.TotalAmountPence,
        Currency = txn.Currency,
        Country = txn.Country,
        OccurredAt = txn.OccurredAt,
    };

    private static Order NewOrder(PaymentTransaction txn, string? packId, long amountPence) => new()
    {
        PaymentProvider = txn.Provider,
        ProviderTransactionId = txn.TransactionId,
        BuyerEmail = txn.BuyerEmail,
        PackId = packId,
        AmountPence = amountPence,
        Currency = txn.Currency,
        Country = txn.Country,
        Status = OrderStatus.Paid,
    };
}
