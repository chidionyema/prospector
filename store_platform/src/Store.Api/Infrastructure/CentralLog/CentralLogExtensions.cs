using System.Net.Http.Headers;
using Microsoft.Extensions.DependencyInjection.Extensions;
using OpenTelemetry;
using OpenTelemetry.Exporter;
using OpenTelemetry.Logs;
using OpenTelemetry.Resources;

namespace Store.Api.Infrastructure.CentralLog;

public static class CentralLogExtensions
{
    /// <summary>
    /// Wires the central log producer: our own NDJSON shipper, or the OTLP exporter, never both.
    /// </summary>
    /// <remarks>
    /// Safe to call unconditionally. With no ingest URL or no <c>STORE_INTERNAL_API_KEY</c>
    /// neither transport is registered, so a developer run and CI ship nothing without anyone
    /// remembering to switch it off.
    /// </remarks>
    public static IServiceCollection AddCentralLog(this IServiceCollection services, IConfiguration configuration)
    {
        var options = CentralLogOptions.FromConfiguration(configuration);
        services.TryAddSingleton(options);
        services.AddHttpContextAccessor();

        if (options.Transport == CentralLogTransport.Otlp)
        {
            AddOtlp(services, options);
            return services;
        }

        services.TryAddSingleton(sp => new CentralLogBuffer(sp.GetRequiredService<CentralLogOptions>()));
        services.AddSingleton<ILoggerProvider, CentralLogProvider>();
        services.AddHostedService<CentralLogShipper>();
        return services;
    }

    private static void AddOtlp(IServiceCollection services, CentralLogOptions options)
    {
        // The NDJSON path checks Enabled per record, inside a provider that is always
        // registered. The OTLP exporter has no such check, so the guard has to be here: an
        // exporter registered with a blank endpoint retries a connection every batch interval
        // for the life of the process.
        if (!options.Enabled) return;

        var endpoint = options.ResolvedOtlpEndpoint;
        if (string.IsNullOrWhiteSpace(endpoint)) return;

        services.AddLogging(logging =>
        {
            // The one place self-referential categories are refused. A processor cannot drop a
            // record, so it has to happen at the filter. Same predicate as the NDJSON logger,
            // called rather than copied: logging the exporter's own HTTP failure through the
            // exporter fills the batch with reports of the batch filling.
            logging.AddFilter<OpenTelemetryLoggerProvider>((category, level) =>
                level >= options.MinimumLevel
                && !CentralLogMapper.IsSelfReferential(category ?? ""));

            logging.AddOpenTelemetry(otel =>
            {
                // Without this the exported body is the un-interpolated template, so `msg`
                // would arrive as "order {OrderId} paid" on every line.
                otel.IncludeFormattedMessage = true;
                otel.IncludeScopes = false;

                otel.SetResourceBuilder(ResourceBuilder.CreateDefault()
                    .AddService(serviceName: options.Svc));

                otel.AddProcessor(sp => new CentralLogOtlpProcessor(
                    sp.GetRequiredService<IHttpContextAccessor>()));

                otel.AddOtlpExporter((exporter, processor) => Configure(exporter, processor, options, endpoint));
            });
        });
    }

    private static void Configure(
        OtlpExporterOptions exporter,
        LogRecordExportProcessorOptions processor,
        CentralLogOptions options,
        string endpoint)
    {
        exporter.Endpoint = new Uri(endpoint);

        // Measured 2026-08-20: OpenTelemetry .NET 1.15.3 offers Grpc and HttpProtobuf only.
        // There is no HttpJson, which is why the engine's ingest had to learn protobuf and not
        // just OTLP-shaped JSON.
        exporter.Protocol = OtlpExportProtocol.HttpProtobuf;

        // The key goes on a real header object rather than into OtlpExporterOptions.Headers,
        // which is a comma-separated key=value string. A bearer token containing a comma would
        // be silently split into two broken headers, and the failure would look like an auth
        // problem at the ingest.
        exporter.HttpClientFactory = () =>
        {
            var client = new HttpClient { Timeout = options.Timeout };
            client.DefaultRequestHeaders.Authorization =
                new AuthenticationHeaderValue("Bearer", options.ApiKey);
            return client;
        };

        // The same three numbers the NDJSON shipper is given, so switching transport does not
        // silently change how much is held in memory or how long a line waits.
        processor.ExportProcessorType = ExportProcessorType.Batch;
        processor.BatchExportProcessorOptions.MaxExportBatchSize = options.BatchSize;
        processor.BatchExportProcessorOptions.MaxQueueSize = options.Capacity;
        processor.BatchExportProcessorOptions.ScheduledDelayMilliseconds =
            (int)options.Interval.TotalMilliseconds;
        processor.BatchExportProcessorOptions.ExporterTimeoutMilliseconds =
            (int)options.Timeout.TotalMilliseconds;
    }
}
