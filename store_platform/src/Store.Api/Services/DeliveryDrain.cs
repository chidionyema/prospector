using System.Globalization;
using Microsoft.EntityFrameworkCore;
using Store.Catalog.Domain;
using Store.Catalog.Persistence;

namespace Store.Api.Services;

/// <summary>
/// The ONLY sender of the fulfilment magic link. Reads the delivery outbox
/// (<see cref="PendingDelivery"/>) and sends what is still owed.
///
/// Why this exists rather than an inline send in the webhook handler: the inline send ran after
/// the fulfilment commit and outside it, so the window between "entitlement committed" and "email
/// sent" lost the link permanently. The provider's retry cannot recover it -- the webhook dedup
/// short-circuits to ALREADY_PROCESSED before reaching any send. That window is not theoretical:
/// the API runs a single machine on SQLite (deploy/fly/api.fly.toml), so every deploy is a
/// SIGTERM through it.
///
/// Draining is idempotent by construction: <see cref="PendingDelivery.SentAt"/> is written only
/// after a successful send, so a crash mid-drain costs at worst a duplicate email. For a link a
/// buyer has already paid for, a duplicate is the correct side of that trade.
///
/// Failures are counted, never swallowed: <see cref="PendingDelivery.Attempts"/> and
/// <see cref="PendingDelivery.LastError"/> record why, and a row that exhausts its attempts is
/// logged CRITICAL rather than dropping out of the query in silence.
/// </summary>
public sealed class DeliveryDrain(
    StoreDbContext db,
    IEmailSender emailSender,
    IConfiguration config,
    ILogger<DeliveryDrain> logger)
{
    /// <summary>Rows taken per pass. Bounded so one drain cannot hold the single SQLite writer.</summary>
    private const int BatchSize = 50;

    public async Task<DeliveryDrainResult> DrainAsync(CancellationToken ct = default)
    {
        var storeUrl = config["Store:PublicUrl"] ?? Environment.GetEnvironmentVariable("STORE_PUBLIC_URL");
        var maxAttempts = ReadInt("Delivery:MaxAttempts", 10);

        var due = await db.PendingDeliveries
            .Where(d => d.SentAt == null && d.Attempts < maxAttempts)
            .OrderBy(d => d.Id)
            .Take(BatchSize)
            .ToListAsync(ct)
            .ConfigureAwait(false);

        if (due.Count == 0)
        {
            return new DeliveryDrainResult(0, 0, 0);
        }

        // Both of these leave the rows QUEUED rather than consuming an attempt: the delivery is
        // owed and the configuration is what is broken, so burning attempts here would retire
        // real obligations for a fault that has nothing to do with them. The outbox is the
        // backlog that gets sent the moment the config is fixed.
        if (string.IsNullOrEmpty(storeUrl) || !emailSender.IsConfigured)
        {
            logger.LogError(
                "FULFILMENT-EMAIL-SKIPPED for {Count} queued delivery/deliveries: "
                + "Store:PublicUrl set: {HasUrl}, email sender configured: {HasSender}. "
                + "The links stay queued and will be sent once this is fixed.",
                due.Count, !string.IsNullOrEmpty(storeUrl), emailSender.IsConfigured);
            return new DeliveryDrainResult(0, 0, due.Count);
        }

        var baseUrl = storeUrl.TrimEnd('/');
        var sent = 0;
        var failed = 0;

        foreach (var delivery in due)
        {
            ct.ThrowIfCancellationRequested();
            if (await TrySendAsync(delivery, baseUrl, maxAttempts, ct).ConfigureAwait(false))
            {
                sent++;
            }
            else
            {
                failed++;
            }
        }

        await db.SaveChangesAsync(ct).ConfigureAwait(false);
        return new DeliveryDrainResult(sent, failed, due.Count - sent - failed);
    }

    private async Task<bool> TrySendAsync(
        PendingDelivery delivery, string baseUrl, int maxAttempts, CancellationToken ct)
    {
        var orderUrl = $"{baseUrl}/orders/{delivery.GrantToken}";

        var title = await db.Packs
            .Where(p => p.Id == delivery.PackId)
            .Select(p => p.Title)
            .FirstOrDefaultAsync(ct)
            .ConfigureAwait(false) ?? delivery.PackId;

        bool ok;
        string? error = null;
        try
        {
            ok = await emailSender.SendDownloadLinkAsync(delivery.BuyerEmail, title, orderUrl)
                .ConfigureAwait(false);
        }
#pragma warning disable CA1031 // a sender that throws must not stop the rest of the batch
        catch (Exception ex)
#pragma warning restore CA1031
        {
            ok = false;
            error = ex.GetType().Name + ": " + ex.Message;
        }

        if (ok)
        {
            delivery.SentAt = DateTime.UtcNow;
            delivery.LastError = null;
            return true;
        }

        delivery.Attempts++;
        delivery.LastError = Truncate(error ?? "sender returned false", 500);

        if (delivery.Attempts >= maxAttempts)
        {
            // The row now falls out of the drain query, so this is the last time anything says
            // so. A buyer has paid and will never be emailed their link unless an operator acts.
            logger.LogCritical(
                "FULFILMENT-EMAIL-ABANDONED after {Attempts} attempts for {PackId} to {Email}; "
                + "re-issue manually: {OrderUrl} (last error: {LastError})",
                delivery.Attempts, delivery.PackId, delivery.BuyerEmail, orderUrl, delivery.LastError);
        }
        else
        {
            logger.LogError(
                "FULFILMENT-EMAIL-FAILED (attempt {Attempts}) for {PackId} to {Email}; queued for "
                + "retry: {OrderUrl} (error: {LastError})",
                delivery.Attempts, delivery.PackId, delivery.BuyerEmail, orderUrl, delivery.LastError);
        }

        return false;
    }

    private int ReadInt(string key, int fallback) =>
        int.TryParse(config[key], CultureInfo.InvariantCulture, out var value) && value > 0
            ? value
            : fallback;

    private static string Truncate(string value, int max) =>
        value.Length <= max ? value : value[..max];
}
