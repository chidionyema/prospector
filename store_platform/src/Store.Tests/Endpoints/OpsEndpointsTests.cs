using System.Net;
using System.Text.Json;

namespace Store.Tests.Endpoints;

/// <summary>
/// The shop's operator reads: orders, revenue, delivery outbox.
/// </summary>
/// <remarks>
/// These routes exist because every one of these rows was already in the database with no way to
/// reach it. The tests that matter here are not "does it return 200" — they are the three ways a
/// money screen lies:
/// <list type="number">
/// <item>adding two currencies together,</item>
/// <item>calling the sum of the per-pack Order split "revenue" when the transaction took less,</item>
/// <item>handing a buyer's download credential to anything that renders a support screen.</item>
/// </list>
/// </remarks>
public sealed class OpsEndpointsTests : IClassFixture<OpsSeedFixture>
{
    private readonly OpsSeedFixture _seed;

    public OpsEndpointsTests(OpsSeedFixture seed) => _seed = seed;

    private HttpClient Keyed()
    {
        var client = _seed.Factory.CreateClient();
        client.DefaultRequestHeaders.Add("X-Internal-Key", StoreApiFactory.InternalKey);
        return client;
    }

    private async Task<JsonElement> GetAsync(string url)
    {
        var response = await Keyed().GetAsync(url);
        response.EnsureSuccessStatusCode();
        var body = await response.Content.ReadAsStringAsync();
        return JsonDocument.Parse(body).RootElement.Clone();
    }

    /// <summary>
    /// String equality with an explicit comparison, because the analyzers reject bare == on
    /// strings — and because a currency code compared under the current culture is exactly the
    /// kind of thing that works on this laptop and not on a Turkish locale.
    /// </summary>
    private static bool Is(JsonElement element, string property, string value) =>
        string.Equals(element.GetProperty(property).GetString(), value, StringComparison.Ordinal);

    // ------------------------------------------------------------------ the fence

    [Theory]
    [InlineData("/internal/ops/orders")]
    [InlineData("/internal/ops/orders/1")]
    [InlineData("/internal/ops/sales")]
    [InlineData("/internal/ops/deliveries")]
    [InlineData("/internal/ops/disputes")]
    public async Task Every_ops_read_refuses_a_caller_with_no_key(string url)
    {
        // These routes return buyer email addresses. An open one is a breach, not a leaked counter.
        var response = await _seed.Factory.CreateClient().GetAsync(url);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task A_wrong_key_is_refused()
    {
        var client = _seed.Factory.CreateClient();
        client.DefaultRequestHeaders.Add("X-Internal-Key", "not-the-key");

        var response = await client.GetAsync("/internal/ops/orders");

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    // ------------------------------------------------------------------ money rules

    [Fact]
    public async Task Currencies_are_reported_as_separate_buckets_and_never_added_together()
    {
        var root = await GetAsync("/internal/ops/sales?days=30");

        var buckets = root.GetProperty("byCurrency").EnumerateArray()
            .ToDictionary(b => b.GetProperty("currency").GetString()!,
                          b => b.GetProperty("grossMinorUnits").GetInt64(),
                          StringComparer.Ordinal);

        Assert.Equal(2, buckets.Count);
        Assert.Equal(4900 + 6500 + 4900, buckets["GBP"]);
        Assert.Equal(6500, buckets["USD"]);

        // The defect this pins: a single combined figure. 16300 pence and 6500 cents have no sum,
        // and a screen given one would print a number that is true in no currency.
        foreach (var forbidden in new[] { "gross", "grossMinorUnits", "total", "totalMinorUnits" })
        {
            Assert.False(root.TryGetProperty(forbidden, out _),
                $"the sales payload must not carry a cross-currency '{forbidden}'");
        }
    }

    [Fact]
    public async Task Revenue_comes_from_the_transaction_audit_not_from_summing_orders()
    {
        var root = await GetAsync("/internal/ops/sales?days=30");

        var gbpGross = root.GetProperty("byCurrency").EnumerateArray()
            .Single(b => Is(b, "currency", "GBP"))
            .GetProperty("grossMinorUnits").GetInt64();

        var gbpOrderSplit = root.GetProperty("byPack").EnumerateArray()
            .Where(p => Is(p, "currency", "GBP"))
            .Sum(p => p.GetProperty("splitMinorUnits").GetInt64());

        // The seeded cart took 6500 and split 7000 across two packs. If these two ever match,
        // the discounted cart has stopped being seeded and this test has stopped measuring.
        Assert.Equal(16300, gbpGross);
        Assert.Equal(16800, gbpOrderSplit);
        Assert.NotEqual(gbpGross, gbpOrderSplit);
    }

    [Fact]
    public async Task Today_is_carried_by_the_api_not_derived_in_the_browser()
    {
        var root = await GetAsync("/internal/ops/sales?days=30");

        var todayGbp = root.GetProperty("today").EnumerateArray()
            .Single(b => Is(b, "currency", "GBP"));

        // The five-day-old refunded sale is in the window but not in today.
        Assert.Equal(4900 + 6500, todayGbp.GetProperty("grossMinorUnits").GetInt64());
        Assert.Equal(2, todayGbp.GetProperty("transactions").GetInt32());
        Assert.Equal("UTC", root.GetProperty("dayBoundary").GetString());
    }

    [Fact]
    public async Task One_payment_split_across_two_packs_counts_as_one_transaction()
    {
        var root = await GetAsync("/internal/ops/sales?days=30");

        var gbp = root.GetProperty("byCurrency").EnumerateArray()
            .Single(b => Is(b, "currency", "GBP"));

        // txn_solo, txn_cart, txn_refund — three payments, four GBP order rows.
        Assert.Equal(3, gbp.GetProperty("transactions").GetInt32());
    }

    [Fact]
    public async Task Per_pack_rows_count_units_and_flag_refunds()
    {
        var root = await GetAsync("/internal/ops/sales?days=30");

        var alpha = root.GetProperty("byPack").EnumerateArray()
            .Single(p => Is(p, "packId", "pack-alpha")
                && Is(p, "currency", "GBP"));

        Assert.Equal("Alpha pack", alpha.GetProperty("packTitle").GetString());
        Assert.Equal(3, alpha.GetProperty("units").GetInt32());
        Assert.Equal(1, alpha.GetProperty("refunded").GetInt32());
    }

    // ------------------------------------------------------------------ orders

    [Fact]
    public async Task Orders_can_be_found_by_a_fragment_of_the_buyers_email()
    {
        var root = await GetAsync("/internal/ops/orders?q=buyer.us@");

        Assert.Equal(1, root.GetProperty("total").GetInt32());
        var order = root.GetProperty("orders").EnumerateArray().Single();
        Assert.Equal("buyer.us@example.com", order.GetProperty("buyerEmail").GetString());
        Assert.Equal("USD", order.GetProperty("currency").GetString());
    }

    [Fact]
    public async Task A_transaction_id_matches_exactly_and_never_by_fragment()
    {
        // Exact matches.
        var exact = await GetAsync("/internal/ops/orders?q=txn_usd");
        Assert.Equal(1, exact.GetProperty("total").GetInt32());

        // A half-pasted id must not match. Substring matching on transaction ids turns a short
        // paste into a page of somebody else's orders.
        var partial = await GetAsync("/internal/ops/orders?q=txn_us");
        Assert.Equal(0, partial.GetProperty("total").GetInt32());
    }

    [Fact]
    public async Task An_order_carries_its_pack_title_entitlement_and_delivery_state()
    {
        var root = await GetAsync($"/internal/ops/orders?q=buyer.one@example.com");
        var order = root.GetProperty("orders").EnumerateArray().Single();

        Assert.Equal("Alpha pack", order.GetProperty("packTitle").GetString());
        Assert.Equal("Paid", order.GetProperty("status").GetString());
        Assert.Equal(2, order.GetProperty("entitlement").GetProperty("downloadCount").GetInt32());
        Assert.Equal("sent", order.GetProperty("delivery").GetProperty("state").GetString());
    }

    [Fact]
    public async Task An_unknown_status_filter_is_refused_with_the_allowed_values()
    {
        var response = await Keyed().GetAsync("/internal/ops/orders?status=Vanished");

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        var body = await response.Content.ReadAsStringAsync();
        Assert.Contains("Refunded", body, StringComparison.Ordinal);
    }

    [Fact]
    public async Task An_order_detail_shows_the_other_packs_bought_in_the_same_payment()
    {
        var root = await GetAsync($"/internal/ops/orders/{_seed.CartOrderId}");

        var siblings = root.GetProperty("siblings").EnumerateArray().ToList();

        // Refunding "the order" without seeing the other line is how a partial refund becomes a
        // dispute, so the sibling must be on the screen.
        Assert.Single(siblings);
        Assert.Equal("pack-beta", siblings[0].GetProperty("packId").GetString());
    }

    [Fact]
    public async Task An_order_detail_never_returns_the_download_credential()
    {
        var response = await Keyed().GetAsync($"/internal/ops/orders/{_seed.SoloOrderId}");
        var body = await response.Content.ReadAsStringAsync();

        // The grant token IS the download. A support screen does not need it, and a screenshot
        // or a log line carrying one hands over the product.
        Assert.DoesNotContain(OpsSeedFixture.SecretGrantToken, body, StringComparison.Ordinal);
        // ...but the screen must still be able to say whether a credential exists at all.
        Assert.Contains("grantTokenPresent", body, StringComparison.Ordinal);
    }

    [Fact]
    public async Task An_unknown_order_is_a_404_not_an_empty_object()
    {
        var response = await Keyed().GetAsync("/internal/ops/orders/999999");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    // ------------------------------------------------------------------ deliveries

    [Fact]
    public async Task Failed_means_tried_and_still_unsent_which_is_the_population_a_human_chases()
    {
        var root = await GetAsync("/internal/ops/deliveries?state=failed");

        var counts = root.GetProperty("counts");
        Assert.Equal(1, counts.GetProperty("sent").GetInt32());
        Assert.Equal(1, counts.GetProperty("pending").GetInt32());
        Assert.Equal(1, counts.GetProperty("failed").GetInt32());
        // Abandoned is its own number. Rolled into "failed" it would read as something still
        // being retried, when in fact the drain has stopped and no buyer will be served.
        Assert.Equal(1, counts.GetProperty("abandoned").GetInt32());
        Assert.Equal(3, counts.GetProperty("undelivered").GetInt32());

        var failed = root.GetProperty("deliveries").EnumerateArray().Single();
        Assert.Equal("pack-alpha", failed.GetProperty("packId").GetString());
        Assert.Equal(3, failed.GetProperty("attempts").GetInt32());
        Assert.Equal("mailjet returned 500", failed.GetProperty("lastError").GetString());
    }

    [Fact]
    public async Task Unsent_is_the_default_and_covers_both_never_tried_and_failing()
    {
        var root = await GetAsync("/internal/ops/deliveries");

        Assert.Equal("unsent", root.GetProperty("state").GetString());
        Assert.Equal(3, root.GetProperty("deliveries").GetArrayLength());
    }

    /// <summary>
    /// The drain stops at <c>Delivery:MaxAttempts</c>. A row past it is a buyer who paid, holds a
    /// live entitlement, and will never be sent their link by any automatic process — so it must
    /// be reachable as its own population, not buried in "failed".
    /// </summary>
    [Fact]
    public async Task Abandoned_is_the_population_no_automatic_process_will_ever_retry()
    {
        var root = await GetAsync("/internal/ops/deliveries?state=abandoned");

        Assert.Equal(10, root.GetProperty("maxAttempts").GetInt32());
        var row = root.GetProperty("deliveries").EnumerateArray().Single();
        Assert.Equal("abandoned", row.GetProperty("state").GetString());
        Assert.Equal(10, row.GetProperty("attempts").GetInt32());

        // And it is absent from the failed list, which is what makes the split worth anything.
        var failed = await GetAsync("/internal/ops/deliveries?state=failed");
        Assert.DoesNotContain(failed.GetProperty("deliveries").EnumerateArray(),
            d => d.GetProperty("id").GetInt64() == row.GetProperty("id").GetInt64());
    }

    [Fact]
    public async Task The_delivery_list_never_returns_the_grant_token_either()
    {
        var response = await Keyed().GetAsync("/internal/ops/deliveries?state=all");
        var body = await response.Content.ReadAsStringAsync();

        Assert.DoesNotContain(OpsSeedFixture.SecretGrantToken, body, StringComparison.Ordinal);
    }

    /// <summary>
    /// The seeded refund is a whole GBP transaction, so it must appear once with its full audit
    /// amount. Summing the reversed ORDER rows instead would give a different number on any cart.
    /// </summary>
    [Fact]
    public async Task A_refund_shows_the_transaction_it_reversed_not_the_order_split()
    {
        var body = await GetAsync("/internal/ops/disputes?days=30");

        var statuses = body.GetProperty("counts").EnumerateArray()
            .Select(c => c.GetProperty("status").GetString())
            .ToList();
        Assert.Contains("Refunded", statuses);

        var gbp = body.GetProperty("byCurrency").EnumerateArray()
            .Single(c => Is(c, "currency", "GBP"));
        Assert.Equal(4900, gbp.GetProperty("grossMinorUnits").GetInt64());
        Assert.Equal(1, gbp.GetProperty("transactions").GetInt32());
    }

    /// <summary>
    /// The reversal is never persisted — <c>RevokeAsync</c> changes two status fields and the
    /// <c>PaymentReversal</c> record is gone. Every date on this screen is therefore the date of
    /// the original sale, and a dispute clock the operator cannot see is worse than no clock, so
    /// the payload has to say which one it is showing.
    /// </summary>
    [Fact]
    public async Task The_disputes_read_admits_its_dates_are_sale_dates()
    {
        var body = await GetAsync("/internal/ops/disputes");

        Assert.Contains("not timestamped",
            body.GetProperty("dateBasis").GetString() ?? "", StringComparison.Ordinal);
    }

    /// <summary>
    /// A delivery row's own id is not an order id. A console linking to /orders/{id} with the
    /// delivery's id lands on a 404, or on a different buyer's order that happens to share the
    /// number — which is the worse outcome, because it looks like it worked.
    /// </summary>
    [Fact]
    public async Task A_delivery_carries_the_order_it_belongs_to_not_just_its_own_id()
    {
        var body = await GetAsync("/internal/ops/deliveries?state=all");
        var rows = body.GetProperty("deliveries").EnumerateArray().ToList();

        Assert.NotEmpty(rows);
        foreach (var row in rows)
        {
            Assert.True(row.TryGetProperty("orderId", out var orderId),
                "every delivery must name its order");
            Assert.NotEqual(JsonValueKind.Null, orderId.ValueKind);
        }

        var known = rows.Select(r => r.GetProperty("orderId").GetInt64()).ToList();
        Assert.Contains(_seed.CartOrderId, known);

        var mismatched = rows.Count(r => r.GetProperty("id").GetInt64()
            != r.GetProperty("orderId").GetInt64());
        Assert.True(mismatched > 0,
            "the seed must contain a delivery whose row id differs from its order id, "
            + "or this test would pass on an endpoint that returned the wrong number");
    }

    [Fact]
    public async Task An_unknown_delivery_state_is_refused_with_the_allowed_values()
    {
        var response = await Keyed().GetAsync("/internal/ops/deliveries?state=elsewhere");

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        var body = await response.Content.ReadAsStringAsync();
        Assert.Contains("failed", body, StringComparison.Ordinal);
    }
}
