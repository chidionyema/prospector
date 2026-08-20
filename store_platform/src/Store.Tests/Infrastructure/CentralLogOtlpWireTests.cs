using System.Text;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Store.Api.Infrastructure.CentralLog;

namespace Store.Tests.Infrastructure;

/// <summary>
/// Drives the real OpenTelemetry exporter over a real socket and reads the bytes it sent.
/// </summary>
/// <remarks>
/// Everything else about this transport can be asserted against a service collection. This
/// cannot: whether a credential reaches the wire is a fact about the payload, and the payload is
/// produced by a package we did not write. A test that trusted our own processor to have run
/// would pass on a build where the processor was never registered.
/// <para>The captured bytes are also the fixture the engine's decoder is tested against. Set
/// <c>PROSPECTOR_OTLP_CAPTURE</c> to a file path to re-record it; see
/// tests/fixtures/otlp/README.md.</para>
/// </remarks>
public sealed class CentralLogOtlpWireTests
{
    private const string SecretValue = "sk-live-NOT-A-REAL-KEY-0000";

    private sealed record Capture(byte[] Body, string? Authorization, string Path);

    [Fact]
    public async Task A_credential_named_field_never_reaches_the_wire()
    {
        var capture = await Export();
        var text = Encoding.UTF8.GetString(capture.Body);

        Assert.DoesNotContain(SecretValue, text, StringComparison.Ordinal);
        Assert.Contains(CentralLogMapper.Redacted, text, StringComparison.Ordinal);

        // The name still travels. Losing the name as well would hide that a call site is
        // carrying a credential at all, which is the thing an audit needs to see.
        Assert.Contains("stripeApiKey", text, StringComparison.Ordinal);
    }

    [Fact]
    public async Task The_line_carries_the_service_name_the_event_and_the_message()
    {
        var capture = await Export();
        var text = Encoding.UTF8.GetString(capture.Body);

        Assert.Contains("store-api", text, StringComparison.Ordinal);
        Assert.Contains("evt", text, StringComparison.Ordinal);
        Assert.Contains("checkout.started", text, StringComparison.Ordinal);

        // IncludeFormattedMessage. Without it the body is the un-interpolated template and
        // every `msg` in the estate reads "order {OrderId} paid".
        Assert.Contains("order ord_42 paid", text, StringComparison.Ordinal);
    }

    [Fact]
    public async Task The_key_is_presented_as_a_bearer_token_on_the_derived_route()
    {
        var capture = await Export();
        Assert.Equal("Bearer test-ingest-key", capture.Authorization);

        // Measured 2026-08-20: OpenTelemetry .NET 1.15.3 posts to the configured url verbatim
        // and appends no signal path of its own.
        Assert.Equal("/internal/logs/otlp", capture.Path);
    }

    // --- the harness ----------------------------------------------------------------------

    private static async Task<Capture> Export()
    {
        var received = new TaskCompletionSource<Capture>(TaskCreationOptions.RunContinuationsAsynchronously);
        await using var sink = await StartSink(received);
        var origin = Address(sink);

        var services = new ServiceCollection();
        services.AddLogging();
        services.AddCentralLog(new ConfigurationBuilder().AddInMemoryCollection(
            new Dictionary<string, string?>(StringComparer.Ordinal)
            {
                ["Store:CentralLog:Transport"] = "otlp",
                ["Store:CentralLog:Url"] = origin + "/internal/logs",
                ["Store:CentralLog:ApiKey"] = "test-ingest-key",
            }).Build());

        var provider = services.BuildServiceProvider();
        var logger = provider.GetRequiredService<ILoggerFactory>()
            .CreateLogger("Store.Api.Endpoints.CheckoutEndpoints");
        logger.Log(LogLevel.Information, new EventId(1, "checkout.started"), Pairs(), null, Format);

        // Disposing shuts the batch processor down, which exports what is queued. Waiting for
        // the scheduled delay instead would make this test a timing race.
        await provider.DisposeAsync();

        return await received.Task.WaitAsync(TimeSpan.FromSeconds(20));
    }

    private static List<KeyValuePair<string, object?>> Pairs() =>
    [
        new("OrderId", "ord_42"),
        new("stripeApiKey", SecretValue),
        new("{OriginalFormat}", "order {OrderId} paid"),
    ];

    private static string Format(List<KeyValuePair<string, object?>> state, Exception? error) =>
        "order ord_42 paid";

    private static async Task<WebApplication> StartSink(TaskCompletionSource<Capture> received)
    {
        var builder = WebApplication.CreateSlimBuilder();
        builder.WebHost.UseUrls("http://127.0.0.1:0");
        builder.Logging.ClearProviders();
        var app = builder.Build();
        app.MapPost("/internal/logs/otlp", async (HttpContext ctx) =>
        {
            using var buffer = new MemoryStream();
            await ctx.Request.Body.CopyToAsync(buffer);
            received.TrySetResult(new Capture(
                buffer.ToArray(), ctx.Request.Headers.Authorization.ToString(), ctx.Request.Path));
            Record(buffer.ToArray());
            ctx.Response.StatusCode = StatusCodes.Status200OK;
            ctx.Response.ContentType = "application/x-protobuf";
        });
        await app.StartAsync();
        return app;
    }

    private static void Record(byte[] body)
    {
        var path = Environment.GetEnvironmentVariable("PROSPECTOR_OTLP_CAPTURE");
        if (!string.IsNullOrWhiteSpace(path)) File.WriteAllBytes(path, body);
    }

    private static string Address(WebApplication app) =>
        app.Services.GetRequiredService<IServer>()
            .Features.Get<IServerAddressesFeature>()!
            .Addresses.First().TrimEnd('/');
}
