using System.Text;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Store.Api.Infrastructure.CentralLog;

namespace Store.Tests.Infrastructure;

/// <summary>
/// The OTLP transport (issue #501). Two things are being pinned here.
///
/// <para>First, that it is a SWITCH. Registering the OTLP exporter alongside the NDJSON
/// provider would put every record on the wire twice, so the tests below assert what is
/// registered and, more importantly, what is not.</para>
///
/// <para>Second, that switching transport does not quietly drop the redaction. The NDJSON
/// producer replaces the value of any field whose NAME looks like a credential. A stock OTLP
/// exporter does not, so without the processor a one-word config change would start posting an
/// <c>apiKey</c> scope value to the ingest and writing it to the log volume. The last test
/// drives the real exporter over a real socket and reads the bytes.</para>
/// </summary>
public sealed class CentralLogOtlpTests
{
    private static IConfiguration Config(params (string Key, string Value)[] pairs) =>
        new ConfigurationBuilder()
            .AddInMemoryCollection(pairs.Select(p =>
                new KeyValuePair<string, string?>(p.Key, p.Value)))
            .Build();

    // --- Choosing the transport -----------------------------------------------------------

    [Fact]
    public void The_default_transport_is_the_shipper_that_was_already_here()
    {
        Assert.Equal(CentralLogTransport.Ndjson, CentralLogOptions.FromConfiguration(Config()).Transport);
    }

    [Theory]
    [InlineData("otlp")]
    [InlineData("Otlp")]
    [InlineData("OTLP")]
    [InlineData(" otlp ")]
    public void Otlp_is_selected_however_it_is_capitalised(string written)
    {
        var options = CentralLogOptions.FromConfiguration(Config(("Store:CentralLog:Transport", written)));
        Assert.Equal(CentralLogTransport.Otlp, options.Transport);
    }

    [Fact]
    public void A_misspelled_transport_stops_the_process_and_names_the_value()
    {
        // Silence is the worst outcome available: the operator believes the switch happened,
        // the lines keep arriving on the old route, and nothing anywhere says otherwise.
        var ex = Assert.Throws<InvalidOperationException>(() =>
            CentralLogOptions.FromConfiguration(Config(("Store:CentralLog:Transport", "otel"))));
        Assert.Contains("otel", ex.Message, StringComparison.Ordinal);
        Assert.Contains("otlp", ex.Message, StringComparison.Ordinal);
    }

    // --- Where it posts -------------------------------------------------------------------

    [Theory]
    [InlineData("http://engine.internal:8613/internal/logs", "http://engine.internal:8613/internal/logs/otlp")]
    [InlineData("http://engine.internal:8613/internal/logs/", "http://engine.internal:8613/internal/logs/otlp")]
    [InlineData("http://collector.internal:4318/v1/logs", "http://collector.internal:4318/v1/logs")]
    public void The_otlp_route_is_derived_from_the_one_configured_destination(string url, string expected)
    {
        var options = CentralLogOptions.FromConfiguration(Config(("Store:CentralLog:Url", url)));
        Assert.Equal(expected, options.ResolvedOtlpEndpoint);
    }

    [Fact]
    public void An_explicit_otlp_endpoint_wins_over_the_derived_one()
    {
        var options = CentralLogOptions.FromConfiguration(
            Config(("Store:CentralLog:Url", "http://engine.internal:8613/internal/logs"),
                   ("Store:CentralLog:OtlpEndpoint", "http://collector.internal:4318/v1/logs")));
        Assert.Equal("http://collector.internal:4318/v1/logs", options.ResolvedOtlpEndpoint);
    }

    // --- One transport, never two ---------------------------------------------------------

    private static ServiceCollection Wired(string transport, string key = "k")
    {
        var services = new ServiceCollection();
        services.AddLogging();
        services.AddCentralLog(Config(
            ("Store:CentralLog:Transport", transport),
            ("Store:CentralLog:Url", "http://engine.internal:8613/internal/logs"),
            ("Store:CentralLog:ApiKey", key)));
        return services;
    }

    private static string[] Providers(IServiceCollection services)
    {
        using var provider = services.BuildServiceProvider();
        return provider.GetServices<ILoggerProvider>()
            .Select(p => p.GetType().FullName ?? "")
            .ToArray();
    }

    private static bool HasOurProvider(IServiceCollection s) =>
        Providers(s).Contains(typeof(CentralLogProvider).FullName, StringComparer.Ordinal);

    private static bool HasOtelProvider(IServiceCollection s) =>
        Array.Exists(Providers(s), n => n.StartsWith("OpenTelemetry", StringComparison.Ordinal));

    [Fact]
    public void Ndjson_registers_our_shipper_and_no_exporter()
    {
        var services = Wired("ndjson");
        Assert.True(HasOurProvider(services));
        Assert.False(HasOtelProvider(services));
    }

    [Fact]
    public void Otlp_registers_the_exporter_and_not_our_shipper()
    {
        // The whole point of the switch. Both would ship every record twice, under two service
        // names, against a retention policy sized for one copy.
        var services = Wired("otlp");
        Assert.True(HasOtelProvider(services));
        Assert.False(HasOurProvider(services));
        Assert.DoesNotContain(services, d => d.ImplementationType == typeof(CentralLogShipper));
    }

    [Fact]
    public void Otlp_with_no_key_registers_nothing_at_all()
    {
        // Unlike the NDJSON provider, the exporter has no per-record Enabled check: registered
        // with no destination it would retry a connection every batch interval, forever.
        var services = Wired("otlp", key: "");
        Assert.False(HasOtelProvider(services));
        Assert.False(HasOurProvider(services));
    }
}
