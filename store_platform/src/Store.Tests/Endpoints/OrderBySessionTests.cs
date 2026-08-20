using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.Extensions.DependencyInjection;
using Store.Catalog.Domain;
using Store.Catalog.Persistence;

namespace Store.Tests.Endpoints;

/// <summary>
/// What the buyer is told after paying. This endpoint is the storefront success page's only
/// source of truth, and it had no test at all.
/// </summary>
/// <remarks>
/// Written after a real 50p live purchase on 2026-07-31 left the account and delivered nothing:
/// the underpayment fence (FulfilmentService.cs:88) refused the entitlement because 50p was
/// below the pack's 4900p list price, so an Order existed with no entitlement row. The endpoint
/// collapsed that into "pending", the page polled for its full timeout and then blamed lag —
/// telling the buyer to wait for something that was never coming.
/// <para>
/// The distinction these tests pin is the whole fix: "pending" must mean a webhook genuinely
/// still in flight, and the two states nothing further can resolve must say so at once.
/// </para>
/// </remarks>
public sealed class OrderBySessionTests : IClassFixture<StoreApiFactory>
{
    private readonly StoreApiFactory _factory;

    public OrderBySessionTests(StoreApiFactory factory) => _factory = factory;

    private async Task<string> ReadStatusAsync(string sessionId)
    {
        var response = await _factory.CreateClient().GetAsync($"/api/orders/by-session/{sessionId}");
        response.EnsureSuccessStatusCode();
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        return doc.RootElement.GetProperty("status").GetString()!;
    }

    /// <summary>Seeds a paid order for <paramref name="sessionId"/>, plus whatever entitlements the test wants on it.</summary>
    private async Task SeedPaidOrderAsync(string sessionId, params EntitlementStatus[] entitlementStatuses)
    {
        var txn = $"txn_{sessionId}";
        _factory.Payments.PaidTransactions[sessionId] = txn;

        using var scope = _factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<StoreDbContext>();

        var order = new Order
        {
            ProviderTransactionId = txn,
            PaymentProvider = "stripe",
            Currency = "gbp",
            AmountPence = 50,
            PackId = "pack-x",
        };
        db.Orders.Add(order);

        foreach (var (status, i) in entitlementStatuses.Select((s, i) => (s, i)))
        {
            db.Entitlements.Add(new Entitlement
            {
                Order = order,
                PackId = "pack-x",
                GrantToken = $"grant_{sessionId}_{i}",
                Status = status,
                ContentKey = "packs/pack-x/abc.zip",
            });
        }

        await db.SaveChangesAsync();
    }

    [Fact]
    public async Task An_unknown_session_is_pending_not_an_error()
    {
        // The browser returns from the payment provider before the webhook lands, so "I have
        // never heard of this session" is the normal FIRST answer and must keep the page polling.
        Assert.Equal("pending", await ReadStatusAsync("cs_never_seen"));
    }

    [Fact]
    public async Task A_paid_session_with_no_order_yet_is_pending()
    {
        // Paid at the rail, webhook genuinely still in flight: the one case polling is for.
        _factory.Payments.PaidTransactions["cs_paid_no_order"] = "txn_not_written_yet";

        Assert.Equal("pending", await ReadStatusAsync("cs_paid_no_order"));
    }

    [Fact]
    public async Task An_order_that_granted_nothing_is_unfulfilled_not_pending()
    {
        // The 50p live purchase. Fulfilment writes the Order and any entitlement in ONE
        // SaveChangesAsync (FulfilmentService.cs:63-64, :109), so an order with zero
        // entitlement rows is not mid-flight — it ran and granted nothing. Answering "pending"
        // here is what made a buyer watch a spinner for a download that could never arrive.
        await SeedPaidOrderAsync("cs_unfulfilled");

        Assert.Equal("unfulfilled", await ReadStatusAsync("cs_unfulfilled"));
    }

    [Fact]
    public async Task An_order_whose_entitlements_are_all_revoked_is_revoked()
    {
        // Granted, then withdrawn by a refund or dispute. Also terminal, but a different thing
        // to say: nothing is owed, and it is not our failure.
        await SeedPaidOrderAsync("cs_revoked", EntitlementStatus.Revoked);

        Assert.Equal("revoked", await ReadStatusAsync("cs_revoked"));
    }

    [Fact]
    public async Task A_fulfilled_order_is_ready_with_a_working_download_path()
    {
        await SeedPaidOrderAsync("cs_ready", EntitlementStatus.Active);

        var response = await _factory.CreateClient().GetAsync("/api/orders/by-session/cs_ready");
        response.EnsureSuccessStatusCode();
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());

        Assert.Equal("ready", doc.RootElement.GetProperty("status").GetString());
        var item = Assert.Single(doc.RootElement.GetProperty("items").EnumerateArray().ToList());
        Assert.Equal("/download/grant_cs_ready_0", item.GetProperty("downloadPath").GetString());
        Assert.Equal("/orders/grant_cs_ready_0", item.GetProperty("orderPath").GetString());
    }

    [Fact]
    public async Task A_partly_revoked_order_still_serves_what_is_still_active()
    {
        // Mixed states must not collapse to a terminal answer: one revoked line cannot take a
        // download the buyer still holds.
        await SeedPaidOrderAsync("cs_mixed", EntitlementStatus.Revoked, EntitlementStatus.Active);

        var response = await _factory.CreateClient().GetAsync("/api/orders/by-session/cs_mixed");
        response.EnsureSuccessStatusCode();
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());

        Assert.Equal("ready", doc.RootElement.GetProperty("status").GetString());
        var item = Assert.Single(doc.RootElement.GetProperty("items").EnumerateArray().ToList());
        Assert.Equal("/download/grant_cs_mixed_1", item.GetProperty("downloadPath").GetString());
    }
}
