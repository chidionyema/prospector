using System.Globalization;
using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Store.Catalog.Domain;
using Store.Catalog.Persistence;

namespace Store.Tests.Endpoints;

/// <summary>
/// The one write on the shop's operator surface: put a delivery back in front of the drain.
///
/// Each test owns its own database. These tests mutate rows, and sharing a seed with
/// <see cref="OpsEndpointsTests"/> would make that class's counts depend on the order xUnit
/// happened to run them in — a test suite that passes or fails by luck.
///
/// What is worth pinning here is not "does it return 200". It is that a sent delivery's
/// <c>SentAt</c> survives. That timestamp is the receipt that a link went out, and clearing it to
/// force a retry would destroy the only evidence of the first send.
/// </summary>
public sealed class OpsResendTests
{
    private static async Task<(StoreApiFactory Factory, long DeliveryId, long EntitlementId)>
        SeedAsync(DateTime? sentAt, int attempts, EntitlementStatus status = EntitlementStatus.Active)
    {
        var factory = new StoreApiFactory();
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<StoreDbContext>();

        var order = new Order
        {
            ProviderTransactionId = "txn_resend",
            BuyerEmail = "buyer@example.com",
            PackId = "pack-alpha",
            AmountPence = 4900,
            Currency = "gbp",
            Country = "GB",
            Status = OrderStatus.Paid,
            CreatedAt = DateTime.UtcNow,
        };
        var entitlement = new Entitlement
        {
            Order = order,
            PackId = "pack-alpha",
            BuyerEmail = order.BuyerEmail,
            GrantToken = "grant_token_for_resend",
            ContentKey = "packs/pack-alpha/content.zip",
            Status = status,
        };
        var delivery = new PendingDelivery
        {
            Entitlement = entitlement,
            PackId = "pack-alpha",
            BuyerEmail = order.BuyerEmail,
            GrantToken = entitlement.GrantToken,
            SentAt = sentAt,
            Attempts = attempts,
            LastError = attempts > 0 ? "mailjet returned 500" : null,
        };

        db.Orders.Add(order);
        db.Entitlements.Add(entitlement);
        db.PendingDeliveries.Add(delivery);
        await db.SaveChangesAsync();

        return (factory, delivery.Id, entitlement.Id);
    }

    private static HttpClient Keyed(StoreApiFactory factory)
    {
        var client = factory.CreateClient();
        client.DefaultRequestHeaders.Add("X-Internal-Key", StoreApiFactory.InternalKey);
        return client;
    }

    private static async Task<JsonElement> BodyAsync(HttpResponseMessage response)
    {
        var body = await response.Content.ReadAsStringAsync();
        return JsonDocument.Parse(body).RootElement.Clone();
    }

    [Fact]
    public async Task Resending_is_key_gated_like_every_other_ops_route()
    {
        var (factory, deliveryId, _) = await SeedAsync(sentAt: null, attempts: 0);
        using var _factory = factory;

        var response = await factory.CreateClient()
            .PostAsync($"/internal/ops/deliveries/{deliveryId}/resend", content: null);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    /// <summary>
    /// An abandoned row is the reason this endpoint exists: the drain filters on
    /// <c>Attempts &lt; maxAttempts</c>, so resetting the count is the whole mechanism. No new
    /// row, because the buyer was never sent anything.
    /// </summary>
    [Fact]
    public async Task An_abandoned_delivery_is_requeued_by_resetting_its_attempts()
    {
        var (factory, deliveryId, _) = await SeedAsync(sentAt: null, attempts: 10);
        using var _factory = factory;

        var response = await Keyed(factory)
            .PostAsync($"/internal/ops/deliveries/{deliveryId}/resend", content: null);
        response.EnsureSuccessStatusCode();
        var body = await BodyAsync(response);

        Assert.Equal("requeued", body.GetProperty("action").GetString());
        Assert.Equal(deliveryId, body.GetProperty("deliveryId").GetInt64());

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<StoreDbContext>();
        var rows = await db.PendingDeliveries.AsNoTracking().ToListAsync();

        Assert.Single(rows);
        Assert.Equal(0, rows[0].Attempts);
        Assert.Null(rows[0].LastError);
        Assert.Null(rows[0].SentAt);
    }

    /// <summary>
    /// Resending an already-sent link cannot queue a second row, because
    /// <c>PendingDeliveries.EntitlementId</c> is UNIQUE and that index is what makes enqueueing
    /// idempotent against a duplicate webhook (StoreDbContext.cs:61). So the row is reset, and the
    /// timestamp it is about to lose comes back in the response instead of vanishing.
    /// </summary>
    [Fact]
    public async Task Resending_a_sent_delivery_resets_the_one_row_and_hands_back_its_send_time()
    {
        var sentAt = DateTime.UtcNow.AddHours(-3);
        var (factory, deliveryId, entitlementId) = await SeedAsync(sentAt, attempts: 1);
        using var _factory = factory;

        var response = await Keyed(factory)
            .PostAsync($"/internal/ops/deliveries/{deliveryId}/resend", content: null);
        response.EnsureSuccessStatusCode();
        var body = await BodyAsync(response);

        Assert.Equal("requeued", body.GetProperty("action").GetString());
        Assert.Equal(deliveryId, body.GetProperty("deliveryId").GetInt64());

        // The receipt the row is losing must survive in the response, or the resend destroys the
        // only evidence that the buyer was ever emailed.
        var previous = body.GetProperty("previousSentAt").GetString();
        Assert.NotNull(previous);
        Assert.StartsWith(sentAt.ToString("yyyy-MM-ddTHH:mm", CultureInfo.InvariantCulture),
            previous, StringComparison.Ordinal);

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<StoreDbContext>();
        var rows = await db.PendingDeliveries.AsNoTracking().OrderBy(d => d.Id).ToListAsync();

        Assert.Single(rows);
        Assert.Null(rows[0].SentAt);
        Assert.Equal(0, rows[0].Attempts);
        Assert.Equal(entitlementId, rows[0].EntitlementId);
    }

    /// <summary>
    /// The database, not the endpoint, is the thing that forbids a second outbox row. If this
    /// index is ever dropped, a duplicate webhook can queue the same link twice and this test is
    /// the one that says so.
    /// </summary>
    [Fact]
    public async Task One_entitlement_may_hold_only_one_outbox_row()
    {
        var (factory, _, entitlementId) = await SeedAsync(sentAt: null, attempts: 0);
        using var _factory = factory;

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<StoreDbContext>();
        db.PendingDeliveries.Add(new PendingDelivery
        {
            EntitlementId = entitlementId,
            PackId = "pack-alpha",
            BuyerEmail = "buyer@example.com",
            GrantToken = "grant_token_for_resend_second",
        });

        await Assert.ThrowsAsync<DbUpdateException>(() => db.SaveChangesAsync());
    }

    /// <summary>
    /// A revoked entitlement means the buyer refunded or disputed. Redelivering the download to
    /// someone who took their money back is the one outcome this endpoint must never produce, and
    /// the refusal belongs at the API rather than in a console that could be bypassed.
    /// </summary>
    [Fact]
    public async Task A_refunded_buyer_cannot_be_resent_their_download()
    {
        var (factory, deliveryId, _) =
            await SeedAsync(sentAt: null, attempts: 2, status: EntitlementStatus.Revoked);
        using var _factory = factory;

        var response = await Keyed(factory)
            .PostAsync($"/internal/ops/deliveries/{deliveryId}/resend", content: null);

        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<StoreDbContext>();
        var row = await db.PendingDeliveries.AsNoTracking().SingleAsync();
        Assert.Equal(2, row.Attempts);
    }

    [Fact]
    public async Task An_unknown_delivery_is_a_404_not_a_silent_success()
    {
        var (factory, _, _) = await SeedAsync(sentAt: null, attempts: 0);
        using var _factory = factory;

        var response = await Keyed(factory)
            .PostAsync("/internal/ops/deliveries/999999/resend", content: null);

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }
}
