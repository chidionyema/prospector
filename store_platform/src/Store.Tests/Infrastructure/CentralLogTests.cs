using System.Text.Json;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using Store.Api.Infrastructure.CentralLog;

namespace Store.Tests.Infrastructure;

/// <summary>
/// The central log producer. Every test here is a failure this estate has already paid for
/// somewhere else: a secret in a transcript, a newline that split one record into two, a log
/// path that took a request down with it.
/// </summary>
public sealed class CentralLogTests
{
    private static readonly string[] DocumentedFields = ["corr", "evt", "lvl", "msg", "svc", "ts"];

    private static CentralLogLine MapWith(
        LogLevel level = LogLevel.Information,
        string category = "Store.Api.Endpoints.CheckoutEndpoints",
        string message = "checkout started",
        Exception? exception = null,
        IReadOnlyList<KeyValuePair<string, object?>>? state = null,
        string? corr = null,
        EventId eventId = default) =>
        CentralLogMapper.Map(
            "store-api", category, level, eventId, message, exception, state, corr,
            new DateTimeOffset(2026, 8, 19, 21, 30, 15, 500, TimeSpan.Zero));

    // --- The wire shape ------------------------------------------------------------------

    [Fact]
    public void A_line_carries_exactly_the_documented_fields_and_never_names_its_own_host()
    {
        var line = MapWith(corr: "abc123");
        using var doc = JsonDocument.Parse(line.ToNdjson());
        var keys = doc.RootElement.EnumerateObject().Select(p => p.Name).OrderBy(k => k, StringComparer.Ordinal).ToArray();

        Assert.Equal(DocumentedFields, keys);

        // `host` is set by the ingest from the connection. A service that names its own host can
        // claim to be a different one, and the ingest would file its lines under that name.
        Assert.DoesNotContain("host", keys);
    }

    [Fact]
    public void Optional_fields_are_omitted_rather_than_sent_as_null()
    {
        using var doc = JsonDocument.Parse(MapWith().ToNdjson());
        Assert.False(doc.RootElement.TryGetProperty("corr", out _));
        Assert.False(doc.RootElement.TryGetProperty("ctx", out _));
    }

    [Fact]
    public void A_newline_in_the_payload_cannot_split_one_record_into_two()
    {
        // NDJSON is delimited by newlines. A message containing one would make the ingest read
        // half a record, fail to parse it, and drop the half that carried the error.
        var line = MapWith(message: "boom\nsecond line\r\nthird");
        var ndjson = line.ToNdjson();

        Assert.Single(ndjson.Split('\n'));
        Assert.DoesNotContain('\r', ndjson);
        JsonDocument.Parse(ndjson);
    }

    [Fact]
    public void A_message_and_a_context_value_are_both_bounded()
    {
        var line = MapWith(
            message: new string('m', 5000),
            state: new[] { new KeyValuePair<string, object?>("blob", new string('c', 5000)) });

        Assert.Equal(2000, line.Msg!.Length);
        Assert.Equal(512, line.Ctx!["blob"].Length);
    }

    // --- Secrets -------------------------------------------------------------------------

    [Theory]
    [InlineData("api_key")]
    [InlineData("StripeSecret")]
    [InlineData("access_token")]
    [InlineData("Password")]
    [InlineData("Authorization")]
    [InlineData("Cookie")]
    [InlineData("session_id")]
    [InlineData("private_pem")]
    [InlineData("db_credential")]
    public void A_field_whose_NAME_looks_like_a_secret_never_travels_with_its_value(string name)
    {
        var line = MapWith(state: new[] { new KeyValuePair<string, object?>(name, "sk_live_REAL_VALUE") });

        Assert.Equal("[redacted]", line.Ctx![name]);
        Assert.DoesNotContain("sk_live_REAL_VALUE", line.ToNdjson(), StringComparison.Ordinal);
    }

    [Fact]
    public void An_ordinary_field_is_not_redacted()
    {
        var line = MapWith(state: new[] { new KeyValuePair<string, object?>("orderId", "ord_42") });
        Assert.Equal("ord_42", line.Ctx!["orderId"]);
    }

    // --- evt is a name you can count -----------------------------------------------------

    [Fact]
    public void Two_records_from_one_call_site_share_an_evt_even_when_their_values_differ()
    {
        // If `evt` varied per order id, counting "how many checkouts failed" would need a regex
        // over free text, which is the reason `evt` exists separately from `msg`.
        var a = MapWith(message: "checkout 111 failed", state: new[] { new KeyValuePair<string, object?>("id", "111") });
        var b = MapWith(message: "checkout 222 failed", state: new[] { new KeyValuePair<string, object?>("id", "222") });

        Assert.Equal(a.Evt, b.Evt);
        Assert.NotEqual(a.Msg, b.Msg);
    }

    [Fact]
    public void An_event_name_is_machine_safe_and_bounded()
    {
        var line = MapWith(eventId: new EventId(7, "Checkout Started! (v2)"));
        Assert.Equal("checkout.started.v2", line.Evt);

        var long_ = MapWith(eventId: new EventId(8, new string('x', 400)));
        Assert.True(long_.Evt.Length <= 128);
    }

    [Fact]
    public void The_uninterpolated_template_is_not_repeated_into_ctx()
    {
        var line = MapWith(state: new[]
        {
            new KeyValuePair<string, object?>("{OriginalFormat}", "checkout {id} failed"),
            new KeyValuePair<string, object?>("id", "111"),
        });

        Assert.False(line.Ctx!.ContainsKey("{OriginalFormat}"));
        Assert.True(line.Ctx.ContainsKey("id"));
    }

    // --- Levels --------------------------------------------------------------------------

    [Theory]
    [InlineData(LogLevel.Trace, "debug")]
    [InlineData(LogLevel.Debug, "debug")]
    [InlineData(LogLevel.Information, "info")]
    [InlineData(LogLevel.Warning, "warn")]
    [InlineData(LogLevel.Error, "error")]
    [InlineData(LogLevel.Critical, "crit")]
    public void Every_level_maps_to_one_the_ingest_declares(LogLevel level, string expected)
    {
        Assert.Equal(expected, CentralLogMapper.Level(level));
    }

    [Fact]
    public void An_exception_travels_as_its_type_and_message_not_its_stack()
    {
        var line = MapWith(exception: new InvalidOperationException("the rail is closed"));
        Assert.Equal("InvalidOperationException", line.Ctx!["exc"]);
        Assert.Equal("the rail is closed", line.Ctx["exc_msg"]);
    }

    // --- The loop guard ------------------------------------------------------------------

    [Theory]
    [InlineData("Store.Api.Infrastructure.CentralLog.CentralLogShipper", true)]
    [InlineData("System.Net.Http.HttpClient.Default.LogicalHandler", true)]
    [InlineData("Store.Api.Endpoints.CheckoutEndpoints", false)]
    public void The_shipper_does_not_log_its_own_failures_through_itself(string category, bool refused)
    {
        // The shipper's only sink is the one that just failed. Shipping its HTTP error fills the
        // buffer with reports of the buffer filling, and evicts the lines describing the outage.
        Assert.Equal(refused, CentralLogMapper.IsSelfReferential(category));
    }

    // --- Off unless deliberately switched on ---------------------------------------------

    [Fact]
    public void Shipping_is_off_until_both_the_destination_and_the_key_are_set()
    {
        var url = new CentralLogOptions { Url = "http://ingest/internal/logs", ApiKey = "" };
        var key = new CentralLogOptions { Url = "", ApiKey = "k" };
        var both = new CentralLogOptions { Url = "http://ingest/internal/logs", ApiKey = "k" };

        Assert.False(url.Enabled);
        Assert.False(key.Enabled);
        Assert.True(both.Enabled);
    }

    [Fact]
    public void A_test_run_with_no_configuration_ships_nothing()
    {
        // No key in configuration and none in the environment means a developer laptop and CI
        // ship nothing without anyone remembering to switch it off.
        var previous = Environment.GetEnvironmentVariable("STORE_INTERNAL_API_KEY");
        Environment.SetEnvironmentVariable("STORE_INTERNAL_API_KEY", null);
        try
        {
            var options = CentralLogOptions.FromConfiguration(
                new ConfigurationBuilder().AddInMemoryCollection().Build());
            Assert.False(options.Enabled);
        }
        finally
        {
            Environment.SetEnvironmentVariable("STORE_INTERNAL_API_KEY", previous);
        }
    }

    [Fact]
    public void The_key_is_the_one_this_service_already_holds_so_logging_adds_no_new_secret()
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>(StringComparer.Ordinal)
            {
                ["Store:InternalApiKey"] = "already-held",
                ["Store:CentralLog:Url"] = "http://ingest/internal/logs",
            })
            .Build();

        var options = CentralLogOptions.FromConfiguration(config);
        Assert.Equal("already-held", options.ApiKey);
        Assert.True(options.Enabled);
    }

    // --- The buffer ----------------------------------------------------------------------

    [Fact]
    public void A_full_buffer_drops_the_oldest_lines_and_keeps_the_newest()
    {
        // During an incident the newest lines describe it. Dropping those to preserve history
        // would leave the operator the run-up and none of the failure.
        var queue = new CentralLogBuffer(new CentralLogOptions { Capacity = 10 });
        for (var i = 0; i < 100; i++) queue.TryEnqueue(MapWith(message: $"line {i}"));

        var drained = queue.DrainAvailable(1000);
        Assert.Equal(10, drained.Count);
        Assert.Equal("line 99", drained[^1].Msg);
        Assert.Equal("line 90", drained[0].Msg);
    }

    [Fact]
    public void Enqueueing_never_throws_so_a_logging_call_cannot_fail_a_request()
    {
        var queue = new CentralLogBuffer(new CentralLogOptions { Capacity = 1 });
        queue.Complete();

        var line = MapWith();
        var ex = Record.Exception(() => queue.TryEnqueue(line));

        Assert.Null(ex);
        Assert.Equal(1, queue.Dropped);
    }
}
