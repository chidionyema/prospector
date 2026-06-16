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
    public async Task<FulfilmentOutcome> FulfilAsync(PaddleTransaction txn)
    {
        ArgumentNullException.ThrowIfNull(txn);

        if (await TransactionAlreadyRecordedAsync(txn.TransactionId).ConfigureAwait(false))
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
        PaddleTransaction txn, PurchasedItem item, List<Entitlement> created, List<string> unfulfilled)
    {
        var pack = item.ProductId is null
            ? null
            : await db.Packs.FirstOrDefaultAsync(p => p.PaddleProductId == item.ProductId).ConfigureAwait(false);

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
        PaddleTransaction txn, IReadOnlyList<Entitlement> created, IReadOnlyList<string> unfulfilled)
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
            if (await TransactionAlreadyRecordedAsync(txn.TransactionId).ConfigureAwait(false))
            {
                return new FulfilmentOutcome(true, [], []);
            }

            throw;
        }

        return new FulfilmentOutcome(false, created, unfulfilled);
    }

    private Task<bool> TransactionAlreadyRecordedAsync(string transactionId) =>
        db.SalesAudits.AnyAsync(s => s.PaddleTransactionId == transactionId);

    private static SalesAudit BuildAudit(PaddleTransaction txn) => new()
    {
        PaddleTransactionId = txn.TransactionId,
        PaddleProductId = txn.Items.Count > 0 ? txn.Items[0].ProductId ?? "" : "",
        AmountPence = txn.TotalAmountPence,
        Currency = txn.Currency,
        Country = txn.Country,
        OccurredAt = txn.OccurredAt,
    };

    private static Order NewOrder(PaddleTransaction txn, string? packId, long amountPence) => new()
    {
        PaddleTransactionId = txn.TransactionId,
        BuyerEmail = txn.BuyerEmail,
        PackId = packId,
        AmountPence = amountPence,
        Currency = txn.Currency,
        Country = txn.Country,
        Status = OrderStatus.Paid,
    };
}
