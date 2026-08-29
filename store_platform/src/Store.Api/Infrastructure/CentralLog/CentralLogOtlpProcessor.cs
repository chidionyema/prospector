using Microsoft.AspNetCore.Http;
using OpenTelemetry;
using OpenTelemetry.Logs;
using Store.Api.Common;

namespace Store.Api.Infrastructure.CentralLog;

/// <summary>
/// Makes an OTLP record carry what a <see cref="CentralLogLine"/> carries.
/// </summary>
/// <remarks>
/// <para>The OTLP exporter on its own ships the message and the state attributes and nothing
/// else. Three things the NDJSON producer does would be LOST by switching transport, and one of
/// them is a security regression, so they are done here instead:</para>
/// <list type="number">
/// <item><description><b>Redaction.</b> <see cref="CentralLogMapper"/> replaces the value of any
/// attribute whose NAME looks like a credential before it goes on the wire. Without this step a
/// switch from <c>ndjson</c> to <c>otlp</c> would start posting an <c>apiKey</c> scope value to
/// the ingest and writing it to the log volume. The same regex is used, from the same class, so
/// the two transports cannot drift on what counts as a secret.</description></item>
/// <item><description><b>The correlation id.</b> Read from the same <c>X-Correlation-Id</c>
/// pipeline as everything else, so one purchase keeps one id across the API's logs, the audit
/// log and Stripe metadata. The engine falls back to the OTLP trace id when this attribute is
/// absent, but a trace id is not the id the rest of the estate greps for.</description></item>
/// <item><description><b>A stable <c>evt</c>.</b> The engine derives <c>evt</c> from an
/// attribute, then the scope name. The scope name is the category, which is stable, but it is
/// not the <c>EventId.Name</c> the caller supplied, so the NDJSON lines and the OTLP lines for
/// the same call site would count as two different events.</description></item>
/// </list>
/// <para>Self-referential categories are NOT dropped here: an OpenTelemetry processor cannot
/// refuse a record. They are filtered out at registration in <see cref="CentralLogExtensions"/>
/// by the same <see cref="CentralLogMapper.IsSelfReferential"/> predicate.</para>
/// </remarks>
public sealed class CentralLogOtlpProcessor : BaseProcessor<LogRecord>
{
    private readonly IHttpContextAccessor _http;

    public CentralLogOtlpProcessor(IHttpContextAccessor http) => _http = http;

    public override void OnEnd(LogRecord record)
    {
        // Wrapped for the same reason CentralLogger.Log is: a throw here would surface as a
        // failure in whatever the record was describing, and in this service that is sometimes
        // the line between taking a payment and recording it.
        try
        {
            var attributes = new List<KeyValuePair<string, object?>>(
                (record.Attributes?.Count ?? 0) + 2);

            if (record.Attributes is not null)
            {
                foreach (var pair in record.Attributes)
                {
                    // Already the basis of `evt`; repeating the un-interpolated template doubles
                    // the line for nothing. Same exclusion as the NDJSON mapper.
                    if (string.Equals(pair.Key, "{OriginalFormat}", StringComparison.Ordinal)) continue;
                    attributes.Add(new KeyValuePair<string, object?>(
                        pair.Key,
                        CentralLogMapper.IsSecretName(pair.Key) ? CentralLogMapper.Redacted : pair.Value));
                }
            }

            attributes.Add(new KeyValuePair<string, object?>(
                "evt", CentralLogMapper.Event(record.CategoryName ?? "", record.EventId)));

            var corr = CurrentCorrelationId();
            if (!string.IsNullOrWhiteSpace(corr))
            {
                attributes.Add(new KeyValuePair<string, object?>("corr", corr));
            }

            record.Attributes = attributes;
        }
        catch
        {
            // Deliberately silent, and deliberately not logged: the only sink available here is
            // the one being written to.
        }
    }

    private string? CurrentCorrelationId()
    {
        try
        {
            return _http.HttpContext?.GetCorrelationId();
        }
        catch (ObjectDisposedException)
        {
            // The request finished while a background continuation was still logging.
            return null;
        }
    }
}
