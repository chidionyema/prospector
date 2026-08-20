namespace Store.Api.Infrastructure.CentralLog;

/// <summary>
/// How this service delivers its lines to the ingest. Exactly one is chosen, never both.
/// </summary>
/// <remarks>
/// Registering the OTLP exporter ALONGSIDE <see cref="CentralLogProvider"/> would put every
/// record on the wire twice, under two service names, and double the log volume the retention
/// policy in docs/LOGGING_AND_RETENTION.md is sized against. So this is a switch, not a flag.
/// </remarks>
public enum CentralLogTransport
{
    /// <summary>The default: our own NDJSON shipper, posting to <c>/internal/logs</c>.</summary>
    Ndjson,

    /// <summary>OpenTelemetry OTLP over HTTP/protobuf, posting to <c>/internal/logs/otlp</c>.</summary>
    Otlp,
}
