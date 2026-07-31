using System.Net;
using System.Net.Http.Json;
using System.Text.Json;

namespace Store.Tests.Endpoints;

/// <summary>
/// The storefront's first measurement: four counters behind an allowlist, and a key-gated
/// summary to read them back.
/// </summary>
/// <remarks>
/// The tests that matter are the fences: a free-text event name must bounce (otherwise the
/// table is a public graffiti wall), and the summary must be closed without the internal key
/// (otherwise our conversion rate is a public number).
/// </remarks>
public sealed class AnalyticsEndpointsTests : IClassFixture<StoreApiFactory>
{
    private readonly StoreApiFactory _factory;

    public AnalyticsEndpointsTests(StoreApiFactory factory) => _factory = factory;

    private HttpClient InternalClient()
    {
        var client = _factory.CreateClient();
        client.DefaultRequestHeaders.Add("X-Internal-Key", StoreApiFactory.InternalKey);
        return client;
    }

    private async Task<HttpResponseMessage> PostEventAsync(object body) =>
        await _factory.CreateClient().PostAsJsonAsync("/events", body);

    [Fact]
    public async Task Allowlisted_event_is_accepted_and_counted()
    {
        var response = await PostEventAsync(new
        {
            name = "sample_cta_clicked",
            path = "/",
            sessionId = "s-123",
        });
        Assert.Equal(HttpStatusCode.Accepted, response.StatusCode);

        var summary = await InternalClient().GetFromJsonAsync<JsonElement>("/internal/analytics/summary?days=1");
        var totals = summary.GetProperty("totals").EnumerateArray().ToList();
        var row = totals.Single(t => string.Equals(t.GetProperty("name").GetString(), "sample_cta_clicked", StringComparison.Ordinal));
        Assert.True(row.GetProperty("count").GetInt32() >= 1);
    }

    [Fact]
    public async Task Unknown_event_name_is_rejected()
    {
        var response = await PostEventAsync(new { name = "drop_table_events" });
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Missing_event_name_is_rejected()
    {
        var response = await PostEventAsync(new { path = "/" });
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Oversize_fields_are_truncated_not_rejected()
    {
        var response = await PostEventAsync(new
        {
            name = "page_view",
            path = "/" + new string('a', 2000),
            sessionId = new string('b', 500),
            meta = new string('c', 5000),
        });
        Assert.Equal(HttpStatusCode.Accepted, response.StatusCode);
    }

    [Fact]
    public async Task Summary_is_closed_without_internal_key()
    {
        var bare = await _factory.CreateClient().GetAsync("/internal/analytics/summary");
        Assert.Equal(HttpStatusCode.Unauthorized, bare.StatusCode);

        var wrongKey = _factory.CreateClient();
        wrongKey.DefaultRequestHeaders.Add("X-Internal-Key", "not-the-key");
        var wrong = await wrongKey.GetAsync("/internal/analytics/summary");
        Assert.Equal(HttpStatusCode.Unauthorized, wrong.StatusCode);
    }

    [Fact]
    public async Task Summary_groups_by_day_and_name()
    {
        Assert.Equal(HttpStatusCode.Accepted, (await PostEventAsync(new { name = "page_view", path = "/" })).StatusCode);
        Assert.Equal(HttpStatusCode.Accepted, (await PostEventAsync(new { name = "checkout_completed", meta = "cs_test_1" })).StatusCode);

        var summary = await InternalClient().GetFromJsonAsync<JsonElement>("/internal/analytics/summary?days=7");
        Assert.Equal(7, summary.GetProperty("days").GetInt32());

        var byDay = summary.GetProperty("byDay").EnumerateArray().ToList();
        Assert.Contains(byDay, r =>
            string.Equals(r.GetProperty("name").GetString(), "checkout_completed", StringComparison.Ordinal) &&
            r.GetProperty("count").GetInt32() >= 1);
    }
}
