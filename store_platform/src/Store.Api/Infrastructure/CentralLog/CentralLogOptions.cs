using System.Globalization;

namespace Store.Api.Infrastructure.CentralLog;

/// <summary>
/// Where the central log goes and how much of it we are willing to hold.
///
/// <para>Configured from <c>Store:CentralLog:*</c> or the matching environment variables. It
/// reuses <c>STORE_INTERNAL_API_KEY</c>, the key this service already presents to the engine
/// (<see cref="Store.Api.Auth.InternalKeyGate"/>), so shipping logs adds no new secret to
/// rotate and no new secret to leak.</para>
/// </summary>
public sealed class CentralLogOptions
{
    /// <summary>The service name every line carries. Must match the ingest's filename rule.</summary>
    public string Svc { get; set; } = "store-api";

    /// <summary>
    /// The ingest. Default is the engine over Fly's private 6PN network, which is why the port
    /// is not published in <c>deploy/engine/fly.toml</c>: logs never cross the public internet.
    /// </summary>
    public string Url { get; set; } = "http://prospector-engine.internal:8613/internal/logs";

    public string ApiKey { get; set; } = "";

    /// <summary>
    /// Lines held in memory before the oldest are dropped. Bounded on purpose: an unbounded
    /// queue turns a slow ingest into this service's out-of-memory kill, which would make the
    /// logging of the money path the thing that stops the money path.
    /// </summary>
    public int Capacity { get; set; } = 5000;

    public int BatchSize { get; set; } = 500;
    public TimeSpan Interval { get; set; } = TimeSpan.FromSeconds(2);
    public TimeSpan Timeout { get; set; } = TimeSpan.FromSeconds(3);

    /// <summary>Records below this level never reach the queue.</summary>
    public LogLevel MinimumLevel { get; set; } = LogLevel.Information;

    /// <summary>
    /// Which shipper carries the lines. One or the other, never both: see
    /// <see cref="CentralLogTransport"/>.
    /// </summary>
    public CentralLogTransport Transport { get; set; } = CentralLogTransport.Ndjson;

    /// <summary>
    /// The OTLP endpoint, when <see cref="Transport"/> is <c>Otlp</c>. Blank means derive it
    /// from <see cref="Url"/>, so one configured destination moves both transports and they
    /// cannot be pointed at two different hosts by accident.
    /// </summary>
    public string OtlpEndpoint { get; set; } = "";

    /// <summary>The OTLP endpoint actually used: the configured one, else derived from <see cref="Url"/>.</summary>
    /// <remarks>
    /// The engine registers the signal path itself as well as the bare route, because an OTLP
    /// client is usually handed a BASE url and appends <c>/v1/logs</c>. Measured 2026-08-20:
    /// OpenTelemetry .NET 1.15.3 appends nothing and posts to the configured url verbatim, so
    /// the value below is the full route and not a base.
    /// </remarks>
    public string ResolvedOtlpEndpoint =>
        string.IsNullOrWhiteSpace(OtlpEndpoint) ? DeriveOtlpEndpoint(Url) : OtlpEndpoint.Trim();

    internal const string NdjsonPath = "/internal/logs";

    internal static string DeriveOtlpEndpoint(string? url)
    {
        var trimmed = (url ?? "").Trim().TrimEnd('/');
        if (trimmed.Length == 0) return "";
        return trimmed.EndsWith(NdjsonPath, StringComparison.Ordinal) ? trimmed + "/otlp" : trimmed;
    }

    /// <summary>
    /// Off unless BOTH the destination and the key are configured. A developer laptop, a test
    /// run and CI therefore ship nothing without anyone remembering to switch it off.
    /// </summary>
    public bool Enabled =>
        !string.IsNullOrWhiteSpace(Url) && !string.IsNullOrWhiteSpace(ApiKey);

    public static CentralLogOptions FromConfiguration(IConfiguration config)
    {
        var o = new CentralLogOptions();
        var section = config.GetSection("Store:CentralLog");
        o.Svc = section["Svc"] ?? Environment.GetEnvironmentVariable("STORE_LOG_SVC") ?? o.Svc;
        o.Url = section["Url"] ?? Environment.GetEnvironmentVariable("PROSPECTOR_LOG_INGEST_URL") ?? o.Url;
        o.ApiKey = section["ApiKey"]
                   ?? config["Store:InternalApiKey"]
                   ?? Environment.GetEnvironmentVariable("STORE_INTERNAL_API_KEY")
                   ?? "";
        if (int.TryParse(section["Capacity"], NumberStyles.Integer, CultureInfo.InvariantCulture, out var cap) && cap > 0) o.Capacity = cap;
        if (int.TryParse(section["BatchSize"], NumberStyles.Integer, CultureInfo.InvariantCulture, out var batch) && batch > 0) o.BatchSize = batch;
        if (Enum.TryParse<LogLevel>(section["MinimumLevel"], ignoreCase: true, out var lvl)) o.MinimumLevel = lvl;

        // A misspelled transport FAILS THE PROCESS rather than silently keeping the default.
        // Silence here is the worst outcome available: the operator who typed it believes the
        // switch happened, the lines keep arriving on the old route, and nothing anywhere says
        // otherwise. Same reason the engine's _build_operator raises on a removed provider name.
        var transport = section["Transport"] ?? Environment.GetEnvironmentVariable("STORE_LOG_TRANSPORT");
        if (!string.IsNullOrWhiteSpace(transport))
        {
            if (!Enum.TryParse<CentralLogTransport>(transport.Trim(), ignoreCase: true, out var chosen))
            {
                throw new InvalidOperationException(
                    $"Store:CentralLog:Transport is '{transport}'. Valid values: "
                    + string.Join(", ", Enum.GetNames<CentralLogTransport>()).ToLowerInvariant());
            }
            o.Transport = chosen;
        }

        o.OtlpEndpoint = section["OtlpEndpoint"]
                         ?? Environment.GetEnvironmentVariable("PROSPECTOR_LOG_OTLP_ENDPOINT")
                         ?? o.OtlpEndpoint;
        return o;
    }
}
