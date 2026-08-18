using System.Globalization;
using Microsoft.EntityFrameworkCore;
using Store.Api.Auth;
using Store.Catalog.Domain;
using Store.Catalog.Persistence;

namespace Store.Api.Endpoints;

/// <summary>
/// The shop's operator surface: orders, revenue and the delivery outbox.
///
/// Why it exists. Every one of these rows was already in the database — <c>Order</c>,
/// <c>Entitlement</c>, <c>SalesAudit</c>, <c>PendingDelivery</c> — and none of it had a route.
/// The only order endpoints were the buyer's own, by grant token or by Stripe session id
/// (<c>DeliveryEndpoints</c>), so the operator could look up an order only if the buyer first
/// handed over their link. There was no list, no search by email, no revenue figure, and no way
/// to see a delivery that never went out. <c>prospector/ops/money.py</c> named the gap in code
/// (<c>MISSING_READS</c>) rather than leaving a blank panel; this closes it.
///
/// Two rules the numbers here obey, because breaking either produces a figure the database
/// disagrees with:
///
/// 1. <b>Money is never summed across currencies.</b> The shop bills GBP and USD
///    (<c>Pack.PriceUsdCents</c>), and a single "gross" number mixing pence and cents is not a
///    smaller truth, it is a wrong one. Every total is bucketed by currency and the caller is
///    given the buckets, never a total of totals.
/// 2. <b>Revenue comes from <see cref="SalesAudit"/>, units come from <see cref="Order"/>.</b>
///    <c>FulfilmentService.cs:31</c> writes ONE audit row per transaction and <c>:64</c> writes
///    one Order per item, so a discounted two-item cart has an audit total below the sum of its
///    Order rows. Summing Orders to get revenue reports money the shop never received.
///
/// The only write here is a delivery resend, which sends nothing itself — it puts a row back in
/// front of the drain. Refunds are not in this file: issuing one needs a rail method that does
/// not exist yet (<c>IPaymentProvider</c> has no refund), and it ships as its own change.
///
/// Gated by <see cref="InternalKeyGate"/>, the same fail-closed <c>X-Internal-Key</c> check as
/// the rest of <c>/internal/*</c>. These routes return buyer email addresses, so an open
/// endpoint here is a data breach rather than a leaked counter.
/// </summary>
public static class OpsEndpoints
{
    /// <summary>Hard ceiling on any page. A console screen that asks for everything gets a page.</summary>
    private const int MaxLimit = 200;

    private static readonly string[] DeliveryStates =
        ["unsent", "pending", "failed", "abandoned", "sent", "all"];

    public static void MapOpsEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/internal/ops/orders", OrdersAsync).WithName("OpsOrders").WithOpenApi();
        app.MapGet("/internal/ops/orders/{id:long}", OrderAsync).WithName("OpsOrder").WithOpenApi();
        app.MapGet("/internal/ops/sales", SalesAsync).WithName("OpsSales").WithOpenApi();
        app.MapGet("/internal/ops/disputes", DisputesAsync).WithName("OpsDisputes").WithOpenApi();
        app.MapGet("/internal/ops/deliveries", DeliveriesAsync).WithName("OpsDeliveries").WithOpenApi();
        app.MapPost("/internal/ops/deliveries/{id:long}/resend", ResendAsync)
            .WithName("OpsResendDelivery").WithOpenApi();
    }

    /// <summary>
    /// The drain's own give-up threshold, read from the key the drain reads
    /// (<c>DeliveryDrain.cs:39</c>). A literal here is how the console would come to call a
    /// delivery "still retrying" that the drain abandoned days ago.
    /// </summary>
    private static int MaxAttempts(IConfiguration config) =>
        int.TryParse(config["Delivery:MaxAttempts"], NumberStyles.Integer,
            CultureInfo.InvariantCulture, out var n) && n > 0 ? n : 10;

    // ----------------------------------------------------------------------- orders

    /// <summary>
    /// The order list, newest first, with the two things an operator always asks next already
    /// joined on: did the buyer get their link, and have they downloaded it.
    /// </summary>
    private static async Task<IResult> OrdersAsync(
        HttpRequest http,
        StoreDbContext db,
        IConfiguration config,
        string? q,
        string? status,
        string? packId,
        DateTime? from,
        DateTime? to,
        int? limit,
        int? offset)
    {
        if (InternalKeyGate.Reject(http, config) is { } rejection)
        {
            return rejection;
        }

        if (!TryParseStatus(status, out var wantedStatus, out var statusError))
        {
            return statusError!;
        }

        var take = limit is null or <= 0 ? 50 : Math.Min(limit.Value, MaxLimit);
        var skip = offset is null or < 0 ? 0 : offset.Value;

        var query = Filtered(db.Orders.AsNoTracking(), q, wantedStatus, packId, from, to);
        var total = await query.CountAsync().ConfigureAwait(false);

        var orders = await query
            .OrderByDescending(o => o.CreatedAt)
            .ThenByDescending(o => o.Id)
            .Skip(skip)
            .Take(take)
            .ToListAsync()
            .ConfigureAwait(false);

        var shaped = await ShapeOrdersAsync(db, orders, MaxAttempts(config)).ConfigureAwait(false);

        return Results.Ok(new
        {
            asOfUtc = Now(),
            total,
            limit = take,
            offset = skip,
            returned = shaped.Count,
            orders = shaped,
        });
    }

    /// <summary>
    /// <paramref name="q"/> matches a buyer email substring or an exact provider transaction id.
    /// Those are the two identifiers a support message ever carries. Matching the transaction id
    /// by substring as well would make a short paste return somebody else's orders.
    /// </summary>
    private static IQueryable<Order> Filtered(
        IQueryable<Order> query, string? q, OrderStatus? status, string? packId,
        DateTime? from, DateTime? to)
    {
        if (!string.IsNullOrWhiteSpace(q))
        {
            var needle = q.Trim();
            query = query.Where(o =>
                EF.Functions.Like(o.BuyerEmail, $"%{needle}%") ||
                o.ProviderTransactionId == needle);
        }

        if (status is { } wanted)
        {
            query = query.Where(o => o.Status == wanted);
        }

        if (!string.IsNullOrWhiteSpace(packId))
        {
            query = query.Where(o => o.PackId == packId);
        }

        if (from is { } fromUtc)
        {
            var fromDate = DateTime.SpecifyKind(fromUtc, DateTimeKind.Utc);
            query = query.Where(o => o.CreatedAt >= fromDate);
        }

        if (to is { } toUtc)
        {
            var toDate = DateTime.SpecifyKind(toUtc, DateTimeKind.Utc);
            query = query.Where(o => o.CreatedAt <= toDate);
        }

        return query;
    }

    private static bool TryParseStatus(string? status, out OrderStatus? parsed, out IResult? error)
    {
        parsed = null;
        error = null;

        if (string.IsNullOrWhiteSpace(status))
        {
            return true;
        }

        if (!Enum.TryParse<OrderStatus>(status, ignoreCase: true, out var wanted))
        {
            error = Results.BadRequest(new
            {
                error = $"unknown status '{status}'",
                allowed = Enum.GetNames<OrderStatus>(),
            });
            return false;
        }

        parsed = wanted;
        return true;
    }

    /// <summary>
    /// One order in full: its entitlements, every delivery attempt behind them, and the sibling
    /// orders that shared the same payment. The siblings matter — a buyer who bought three packs
    /// in one checkout has three Order rows and one card charge, and refunding "the order"
    /// without seeing the other two is how a partial refund becomes a dispute.
    /// </summary>
    private static async Task<IResult> OrderAsync(
        HttpRequest http,
        StoreDbContext db,
        IConfiguration config,
        long id)
    {
        if (InternalKeyGate.Reject(http, config) is { } rejection)
        {
            return rejection;
        }

        var order = await db.Orders.AsNoTracking()
            .FirstOrDefaultAsync(o => o.Id == id)
            .ConfigureAwait(false);

        if (order is null)
        {
            return Results.NotFound(new { error = $"no order {id}" });
        }

        var maxAttempts = MaxAttempts(config);
        var shaped = await ShapeOrdersAsync(db, [order], maxAttempts).ConfigureAwait(false);

        var entitlements = await db.Entitlements.AsNoTracking()
            .Where(e => e.OrderId == order.Id)
            .OrderBy(e => e.Id)
            .ToListAsync()
            .ConfigureAwait(false);

        var entitlementIds = entitlements.ConvertAll(e => e.Id);

        var deliveries = await db.PendingDeliveries.AsNoTracking()
            .Where(d => entitlementIds.Contains(d.EntitlementId))
            .OrderBy(d => d.Id)
            .ToListAsync()
            .ConfigureAwait(false);

        return Results.Ok(new
        {
            asOfUtc = Now(),
            order = shaped[0],
            entitlements = entitlements.ConvertAll(ShapeEntitlement),
            deliveries = deliveries.ConvertAll(d => ShapeDelivery(
                d, maxAttempts, null, entitlements.ToDictionary(e => e.Id, e => e.OrderId))),
            siblings = await SiblingsAsync(db, order).ConfigureAwait(false),
            salesAudit = await AuditAsync(db, order.ProviderTransactionId).ConfigureAwait(false),
        });
    }

    private static async Task<List<object>> SiblingsAsync(StoreDbContext db, Order order)
    {
        var rows = await db.Orders.AsNoTracking()
            .Where(o => o.ProviderTransactionId == order.ProviderTransactionId && o.Id != order.Id)
            .OrderBy(o => o.Id)
            .ToListAsync()
            .ConfigureAwait(false);

        return rows.ConvertAll(o => (object)new
        {
            id = o.Id,
            packId = o.PackId,
            amountMinorUnits = o.AmountPence,
            currency = o.Currency.ToUpperInvariant(),
            status = o.Status.ToString(),
        });
    }

    private static async Task<List<object>> AuditAsync(StoreDbContext db, string transactionId)
    {
        var rows = await db.SalesAudits.AsNoTracking()
            .Where(s => s.ProviderTransactionId == transactionId)
            .OrderBy(s => s.Id)
            .ToListAsync()
            .ConfigureAwait(false);

        return rows.ConvertAll(s => (object)new
        {
            id = s.Id,
            providerProductId = s.ProviderProductId,
            amountMinorUnits = s.AmountPence,
            currency = s.Currency.ToUpperInvariant(),
            country = s.Country,
            occurredAtUtc = Iso(s.OccurredAt),
        });
    }

    // ----------------------------------------------------------------------- sales

    /// <summary>
    /// What the shop took, over a window, bucketed by currency and never totalled across them.
    ///
    /// <c>today</c> is carried separately because it is the number the operator opens the screen
    /// for, and deriving it from <c>byDay</c> in the browser is how a timezone bug puts
    /// yesterday's money on today's tile. The day boundary is UTC, stated in the payload so the
    /// screen can say so rather than guess.
    /// </summary>
    private static async Task<IResult> SalesAsync(
        HttpRequest http,
        StoreDbContext db,
        IConfiguration config,
        int? days)
    {
        if (InternalKeyGate.Reject(http, config) is { } rejection)
        {
            return rejection;
        }

        var windowDays = days is null or <= 0 ? 30 : Math.Min(days.Value, 365);
        var since = DateTime.UtcNow.Date.AddDays(-(windowDays - 1));

        var audits = await db.SalesAudits.AsNoTracking()
            .Where(s => s.OccurredAt >= since)
            .Select(s => new AuditRow(s.AmountPence, s.Currency, s.OccurredAt, s.ProviderTransactionId))
            .ToListAsync()
            .ConfigureAwait(false);

        var orders = await db.Orders.AsNoTracking()
            .Where(o => o.CreatedAt >= since)
            .Select(o => new OrderRow(o.PackId, o.AmountPence, o.Currency, o.Status))
            .ToListAsync()
            .ConfigureAwait(false);

        var today = DateTime.UtcNow.Date;
        var packIds = orders.Where(o => o.PackId != null).Select(o => o.PackId!)
            .Distinct(StringComparer.Ordinal).ToList();

        return Results.Ok(new
        {
            asOfUtc = Now(),
            days = windowDays,
            sinceUtc = Iso(since),
            dayBoundary = "UTC",
            note = "grossMinorUnits is SalesAudit, the authoritative per-transaction total. "
                + "byPack.splitMinorUnits is the per-pack Order split and is a different number. "
                + "Currencies are never summed together.",
            today = CurrencyBuckets(audits.Where(a => a.OccurredAt.Date == today)),
            byCurrency = CurrencyBuckets(audits),
            byDay = DayBuckets(audits),
            byPack = PackBuckets(orders, await TitlesAsync(db, packIds).ConfigureAwait(false)),
            orderStatuses = orders
                .GroupBy(o => o.Status)
                .OrderBy(g => g.Key)
                .Select(g => new { status = g.Key.ToString(), orders = g.Count() })
                .ToList(),
            orderCount = orders.Count,
        });
    }

    private static List<object> CurrencyBuckets(IEnumerable<AuditRow> audits) =>
        audits
            .GroupBy(a => a.Currency.ToUpperInvariant(), StringComparer.Ordinal)
            .OrderBy(g => g.Key, StringComparer.Ordinal)
            .Select(g => (object)new
            {
                currency = g.Key,
                grossMinorUnits = g.Sum(a => a.AmountMinorUnits),
                transactions = g.Select(a => a.TransactionId).Distinct(StringComparer.Ordinal).Count(),
            })
            .ToList();

    private static List<object> DayBuckets(IEnumerable<AuditRow> audits) =>
        audits
            .GroupBy(a => new { Day = a.OccurredAt.Date, Currency = a.Currency.ToUpperInvariant() })
            .OrderBy(g => g.Key.Day)
            .ThenBy(g => g.Key.Currency, StringComparer.Ordinal)
            .Select(g => (object)new
            {
                date = g.Key.Day.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture),
                currency = g.Key.Currency,
                grossMinorUnits = g.Sum(a => a.AmountMinorUnits),
                transactions = g.Select(a => a.TransactionId).Distinct(StringComparer.Ordinal).Count(),
            })
            .ToList();

    /// <summary>
    /// Per-pack money is the Order split, which is the only place it exists. It is labelled
    /// <c>splitMinorUnits</c>, never <c>gross</c>, so nobody adds these up and expects the
    /// SalesAudit total to match.
    /// </summary>
    private static List<object> PackBuckets(
        IEnumerable<OrderRow> orders, Dictionary<string, string> titles) =>
        orders
            .GroupBy(o => new { PackId = o.PackId ?? "(unknown)", Currency = o.Currency.ToUpperInvariant() })
            .Select(g => new
            {
                packId = g.Key.PackId,
                packTitle = titles.TryGetValue(g.Key.PackId, out var t) ? t : null,
                currency = g.Key.Currency,
                units = g.Count(),
                splitMinorUnits = g.Sum(o => o.AmountMinorUnits),
                refunded = g.Count(o => o.Status is OrderStatus.Refunded or OrderStatus.PartiallyRefunded),
                disputed = g.Count(o => o.Status == OrderStatus.Disputed),
            })
            .OrderByDescending(r => r.splitMinorUnits)
            .Select(r => (object)r)
            .ToList();

    // ----------------------------------------------------------------------- disputes

    /// <summary>
    /// Money that came back out: refunds and chargebacks.
    ///
    /// This reads our own database, not Stripe. <c>FulfilmentService.RevokeAsync</c> already
    /// applies every inbound reversal — it revokes the entitlement and moves the order to
    /// <c>Refunded</c> or <c>Disputed</c> — so the shop's own rows already know. Calling Stripe
    /// from a console read would add a network dependency, a rate limit and a second version of
    /// the truth for something the webhook has already recorded.
    ///
    /// The amount at risk is taken from <see cref="SalesAudit"/> for the affected transactions,
    /// not from summing the order rows, for the reason at the top of this file: the audit is the
    /// per-transaction total and the orders are its split.
    ///
    /// One real limitation, stated in the payload rather than papered over: the reversal itself is
    /// not persisted anywhere. <see cref="PaymentReversal"/> is a webhook-time record that changes
    /// two status fields and is then gone, so there is no "disputed at" timestamp. Every date here
    /// is the date of the ORIGINAL SALE. A dispute is time-limited — Stripe's evidence window is
    /// days, not weeks — so an operator sorting by these dates is sorting by the wrong clock.
    /// Closing that needs a stored reversal row and a migration, which is its own change.
    /// </summary>
    private static async Task<IResult> DisputesAsync(
        HttpRequest http,
        StoreDbContext db,
        IConfiguration config,
        int? days)
    {
        if (InternalKeyGate.Reject(http, config) is { } rejection)
        {
            return rejection;
        }

        var windowDays = days is null or <= 0 ? 90 : Math.Min(days.Value, 365);
        var since = DateTime.UtcNow.Date.AddDays(-(windowDays - 1));

        var reversed = await db.Orders.AsNoTracking()
            .Where(o => o.CreatedAt >= since
                && (o.Status == OrderStatus.Disputed
                    || o.Status == OrderStatus.Refunded
                    || o.Status == OrderStatus.PartiallyRefunded))
            .OrderByDescending(o => o.CreatedAt)
            .ThenByDescending(o => o.Id)
            .Take(MaxLimit)
            .ToListAsync()
            .ConfigureAwait(false);

        var audits = await ReversedAuditsAsync(db, reversed).ConfigureAwait(false);

        return Results.Ok(new
        {
            asOfUtc = Now(),
            days = windowDays,
            sinceUtc = Iso(since),
            dateBasis = "order created; the reversal itself is not timestamped anywhere",
            counts = reversed
                .GroupBy(o => o.Status)
                .OrderBy(g => g.Key)
                .Select(g => new { status = g.Key.ToString(), orders = g.Count() })
                .ToList(),
            orderCount = reversed.Count,
            byCurrency = CurrencyBuckets(audits),
            entitlementsRevoked = await db.Entitlements.AsNoTracking()
                .CountAsync(e => e.Status == EntitlementStatus.Revoked)
                .ConfigureAwait(false),
            orders = await ShapeOrdersAsync(db, reversed, MaxAttempts(config)).ConfigureAwait(false),
            note = "byCurrency is the SalesAudit total for every transaction touched by a "
                + "reversal, so a part-refunded cart shows its FULL charge here. It is money at "
                + "risk, not money returned: the amount actually refunded is not recorded.",
        });
    }

    private static async Task<List<AuditRow>> ReversedAuditsAsync(StoreDbContext db, List<Order> reversed)
    {
        var transactionIds = reversed
            .Select(o => o.ProviderTransactionId)
            .Distinct(StringComparer.Ordinal)
            .ToList();

        if (transactionIds.Count == 0)
        {
            return [];
        }

        return await db.SalesAudits.AsNoTracking()
            .Where(s => transactionIds.Contains(s.ProviderTransactionId))
            .Select(s => new AuditRow(s.AmountPence, s.Currency, s.OccurredAt, s.ProviderTransactionId))
            .ToListAsync()
            .ConfigureAwait(false);
    }

    // ----------------------------------------------------------------------- deliveries

    /// <summary>
    /// The delivery outbox, which is the difference between a buyer who paid and a buyer who
    /// received.
    ///
    /// <c>abandoned</c> is split out from <c>failed</c> because they need different things. The
    /// drain stops retrying at <c>Delivery:MaxAttempts</c>, so an abandoned row is a buyer who
    /// paid, holds an entitlement, and will never be sent their link by any automatic process.
    /// Rolled in with "failed" it looks like something still working.
    /// </summary>
    private static async Task<IResult> DeliveriesAsync(
        HttpRequest http,
        StoreDbContext db,
        IConfiguration config,
        string? state,
        int? limit)
    {
        if (InternalKeyGate.Reject(http, config) is { } rejection)
        {
            return rejection;
        }

        var take = limit is null or <= 0 ? 50 : Math.Min(limit.Value, MaxLimit);
        var wanted = (state ?? "unsent").Trim().ToLowerInvariant();
        var maxAttempts = MaxAttempts(config);

        if (!DeliveryStates.Contains(wanted, StringComparer.Ordinal))
        {
            return Results.BadRequest(new { error = $"unknown state '{state}'", allowed = DeliveryStates });
        }

        var counts = await CountsAsync(db, maxAttempts).ConfigureAwait(false);

        var rows = await ByState(db.PendingDeliveries.AsNoTracking(), wanted, maxAttempts)
            .OrderByDescending(d => d.Id)
            .Take(take)
            .ToListAsync()
            .ConfigureAwait(false);

        var titles = await TitlesAsync(
            db, rows.Select(r => r.PackId).Distinct(StringComparer.Ordinal).ToList())
            .ConfigureAwait(false);

        var orderIds = await OrderIdsAsync(db, rows).ConfigureAwait(false);

        return Results.Ok(new
        {
            asOfUtc = Now(),
            state = wanted,
            maxAttempts,
            counts,
            note = "abandoned = the drain gave up. Nothing will retry these without a resend.",
            deliveries = rows.ConvertAll(d => ShapeDelivery(d, maxAttempts, titles, orderIds)),
        });
    }

    private static IQueryable<PendingDelivery> ByState(
        IQueryable<PendingDelivery> query, string wanted, int maxAttempts) => wanted switch
        {
            "sent" => query.Where(d => d.SentAt != null),
            "pending" => query.Where(d => d.SentAt == null && d.Attempts == 0),
            "failed" => query.Where(d => d.SentAt == null && d.Attempts > 0 && d.Attempts < maxAttempts),
            "abandoned" => query.Where(d => d.SentAt == null && d.Attempts >= maxAttempts),
            "unsent" => query.Where(d => d.SentAt == null),
            _ => query,
        };

    private static async Task<object> CountsAsync(StoreDbContext db, int maxAttempts)
    {
        var rows = await db.PendingDeliveries.AsNoTracking()
            .GroupBy(d => new
            {
                Sent = d.SentAt != null,
                Attempted = d.Attempts > 0,
                Spent = d.Attempts >= maxAttempts,
            })
            .Select(g => new { g.Key.Sent, g.Key.Attempted, g.Key.Spent, Count = g.Count() })
            .ToListAsync()
            .ConfigureAwait(false);

        var sent = rows.Where(c => c.Sent).Sum(c => c.Count);
        var pending = rows.Where(c => !c.Sent && !c.Attempted).Sum(c => c.Count);
        var failed = rows.Where(c => !c.Sent && c.Attempted && !c.Spent).Sum(c => c.Count);
        var abandoned = rows.Where(c => !c.Sent && c.Spent).Sum(c => c.Count);

        return new
        {
            sent,
            pending,
            failed,
            abandoned,
            undelivered = pending + failed + abandoned,
        };
    }

    /// <summary>
    /// Put a delivery back in front of the drain.
    ///
    /// Two shapes, because <see cref="PendingDelivery.SentAt"/> is a receipt and a receipt is not
    /// editable. An unsent row is reset to zero attempts, which is all the drain's
    /// <c>Attempts &lt; maxAttempts</c> filter needs to pick it up again. A row that WAS sent gets
    /// a new row instead — clearing <c>SentAt</c> would erase the evidence that the link went
    /// out, and "we already emailed them once" is the fact a support conversation turns on.
    ///
    /// This endpoint sends nothing itself. The drain is the only sender, so redelivery stays a
    /// retry of one code path rather than a second way to email a buyer.
    /// </summary>
    private static async Task<IResult> ResendAsync(
        HttpRequest http,
        StoreDbContext db,
        IConfiguration config,
        long id)
    {
        if (InternalKeyGate.Reject(http, config) is { } rejection)
        {
            return rejection;
        }

        var delivery = await db.PendingDeliveries.FirstOrDefaultAsync(d => d.Id == id)
            .ConfigureAwait(false);

        if (delivery is null)
        {
            return Results.NotFound(new { error = $"no delivery {id}" });
        }

        var entitlement = await db.Entitlements.AsNoTracking()
            .FirstOrDefaultAsync(e => e.Id == delivery.EntitlementId)
            .ConfigureAwait(false);

        if (entitlement is null)
        {
            return Results.Conflict(new
            {
                error = "the entitlement behind this delivery is gone; there is nothing to deliver",
            });
        }

        if (entitlement.Status == EntitlementStatus.Revoked)
        {
            return Results.Conflict(new
            {
                error = "this entitlement is revoked (refunded or disputed) — resend refused",
                entitlementId = entitlement.Id,
            });
        }

        return Results.Ok(await RequeueAsync(db, delivery).ConfigureAwait(false));
    }

    /// <summary>
    /// Resend always reuses the existing outbox row. It cannot queue a second one:
    /// <c>PendingDeliveries.EntitlementId</c> is UNIQUE (StoreDbContext.cs:61) and that index is
    /// what makes enqueueing idempotent against a duplicate webhook. Inserting a second row for
    /// the same entitlement is refused by the database, so the only legal resend is a reset.
    ///
    /// The cost is real and is reported rather than hidden: resending an already-sent delivery
    /// clears <c>SentAt</c>, which was the row-level receipt of the first send. The response
    /// carries <c>previousSentAt</c> so the caller can record it, and the console gateway writes
    /// that into its own intent receipt before the row loses it.
    /// </summary>
    private static async Task<object> RequeueAsync(StoreDbContext db, PendingDelivery delivery)
    {
        var previousSentAt = delivery.SentAt;

        delivery.SentAt = null;
        delivery.Attempts = 0;
        delivery.LastError = null;
        await db.SaveChangesAsync().ConfigureAwait(false);

        return new
        {
            asOfUtc = Now(),
            action = "requeued",
            deliveryId = delivery.Id,
            originalDeliveryId = delivery.Id,
            buyerEmail = delivery.BuyerEmail,
            packId = delivery.PackId,
            previousSentAt = previousSentAt is null ? null : Iso(previousSentAt.Value),
            note = previousSentAt is null
                ? "attempts reset to 0; the delivery drain will pick it up on its next pass"
                : "this link had already been sent; the row is reset and its SentAt receipt is "
                  + "returned as previousSentAt, because one entitlement may hold only one "
                  + "outbox row",
        };
    }

    // ----------------------------------------------------------------------- shaping

    /// <summary>
    /// Joins pack title, entitlement and latest delivery onto a page of orders in three queries,
    /// not three per row. The page is bounded by <see cref="MaxLimit"/>, so the <c>Contains</c>
    /// translations stay well inside SQLite's parameter ceiling.
    /// </summary>
    private static async Task<List<object>> ShapeOrdersAsync(
        StoreDbContext db, List<Order> orders, int maxAttempts)
    {
        if (orders.Count == 0)
        {
            return [];
        }

        var orderIds = orders.ConvertAll(o => o.Id);
        var packIds = orders.Where(o => o.PackId != null).Select(o => o.PackId!)
            .Distinct(StringComparer.Ordinal).ToList();

        var titles = await TitlesAsync(db, packIds).ConfigureAwait(false);

        var entitlements = await db.Entitlements.AsNoTracking()
            .Where(e => orderIds.Contains(e.OrderId))
            .ToListAsync()
            .ConfigureAwait(false);

        var entitlementIds = entitlements.ConvertAll(e => e.Id);

        var deliveries = await db.PendingDeliveries.AsNoTracking()
            .Where(d => entitlementIds.Contains(d.EntitlementId))
            .ToListAsync()
            .ConfigureAwait(false);

        var byOrder = entitlements
            .GroupBy(e => e.OrderId)
            .ToDictionary(g => g.Key, g => g.OrderBy(e => e.Id).ToList());
        var byEntitlement = deliveries
            .GroupBy(d => d.EntitlementId)
            .ToDictionary(g => g.Key, g => g.OrderByDescending(d => d.Id).First());

        var orderOf = entitlements.ToDictionary(e => e.Id, e => e.OrderId);

        return orders.ConvertAll(o =>
            ShapeOrder(o, titles, byOrder, byEntitlement, orderOf, maxAttempts));
    }

    private static object ShapeOrder(
        Order o,
        Dictionary<string, string> titles,
        Dictionary<long, List<Entitlement>> byOrder,
        Dictionary<long, PendingDelivery> byEntitlement,
        Dictionary<long, long> orderOf,
        int maxAttempts)
    {
        byOrder.TryGetValue(o.Id, out var ents);
        var ent = ents?.Count > 0 ? ents[0] : null;
        PendingDelivery? del = null;
        if (ent is not null)
        {
            byEntitlement.TryGetValue(ent.Id, out del);
        }

        string? title = null;
        if (o.PackId is not null)
        {
            titles.TryGetValue(o.PackId, out title);
        }

        return new
        {
            id = o.Id,
            createdAtUtc = Iso(o.CreatedAt),
            buyerEmail = o.BuyerEmail,
            packId = o.PackId,
            packTitle = title,
            amountMinorUnits = o.AmountPence,
            currency = o.Currency.ToUpperInvariant(),
            country = o.Country,
            status = o.Status.ToString(),
            paymentProvider = o.PaymentProvider,
            providerTransactionId = o.ProviderTransactionId,
            entitlementCount = ents?.Count ?? 0,
            entitlement = ent is null ? null : ShapeEntitlement(ent),
            delivery = del is null ? null : ShapeDelivery(del, maxAttempts, titles, orderOf),
        };
    }

    /// <summary>
    /// The grant token is never returned. An operator screen does not need it to answer a support
    /// question, and a screenshot or a log line carrying one hands over the download.
    /// </summary>
    private static object ShapeEntitlement(Entitlement e) => new
    {
        id = e.Id,
        packId = e.PackId,
        status = e.Status.ToString(),
        contentKey = e.ContentKey,
        contentVersion = e.ContentVersion,
        downloadCount = e.DownloadCount,
        lastDownloadedAtUtc = Iso(e.LastDownloadedAt),
        expiresAtUtc = Iso(e.ExpiresAt),
        createdAtUtc = Iso(e.CreatedAt),
        grantTokenPresent = !string.IsNullOrEmpty(e.GrantToken),
    };

    /// <summary>
    /// Carries <c>orderId</c> as well as its own <c>id</c>. A delivery row's id is not an order
    /// id, and a console that links to <c>/orders/{id}</c> using the delivery's id sends the
    /// operator to a 404 — or worse, to a different buyer's order that happens to share the
    /// number. The join costs one query per page.
    /// </summary>
    private static object ShapeDelivery(
        PendingDelivery d,
        int maxAttempts,
        Dictionary<string, string>? titles = null,
        Dictionary<long, long>? orderIds = null)
    {
        string? title = null;
        titles?.TryGetValue(d.PackId, out title);

        long? orderId = null;
        if (orderIds is not null && orderIds.TryGetValue(d.EntitlementId, out var found))
        {
            orderId = found;
        }

        return new
        {
            id = d.Id,
            entitlementId = d.EntitlementId,
            orderId,
            packId = d.PackId,
            packTitle = title,
            buyerEmail = d.BuyerEmail,
            createdAtUtc = Iso(d.CreatedAt),
            sentAtUtc = Iso(d.SentAt),
            ageMinutes = (int)Math.Round((DateTime.UtcNow - d.CreatedAt).TotalMinutes),
            attempts = d.Attempts,
            lastError = d.LastError,
            state = DeliveryState(d, maxAttempts),
        };
    }

    private static async Task<Dictionary<long, long>> OrderIdsAsync(
        StoreDbContext db, List<PendingDelivery> rows)
    {
        var entitlementIds = rows.Select(r => r.EntitlementId).Distinct().ToList();
        if (entitlementIds.Count == 0)
        {
            return [];
        }

        var pairs = await db.Entitlements.AsNoTracking()
            .Where(e => entitlementIds.Contains(e.Id))
            .Select(e => new { e.Id, e.OrderId })
            .ToListAsync()
            .ConfigureAwait(false);

        return pairs.ToDictionary(p => p.Id, p => p.OrderId);
    }

    private static async Task<Dictionary<string, string>> TitlesAsync(
        StoreDbContext db, List<string> packIds)
    {
        if (packIds.Count == 0)
        {
            return new Dictionary<string, string>(StringComparer.Ordinal);
        }

        var rows = await db.Packs.AsNoTracking()
            .Where(p => packIds.Contains(p.Id))
            .Select(p => new { p.Id, p.Title })
            .ToListAsync()
            .ConfigureAwait(false);

        return rows.ToDictionary(r => r.Id, r => r.Title, StringComparer.Ordinal);
    }

    private static string DeliveryState(PendingDelivery d, int maxAttempts)
    {
        if (d.SentAt is not null)
        {
            return "sent";
        }

        if (d.Attempts >= maxAttempts)
        {
            return "abandoned";
        }

        return d.Attempts > 0 ? "failed" : "pending";
    }

    private static string Now() => Iso(DateTime.UtcNow)!;

    private static string? Iso(DateTime? value) =>
        value is null
            ? null
            : DateTime.SpecifyKind(value.Value, DateTimeKind.Utc)
                .ToString("yyyy-MM-ddTHH:mm:ssZ", CultureInfo.InvariantCulture);

    private sealed record AuditRow(
        long AmountMinorUnits, string Currency, DateTime OccurredAt, string TransactionId);

    private sealed record OrderRow(
        string? PackId, long AmountMinorUnits, string Currency, OrderStatus Status);
}
