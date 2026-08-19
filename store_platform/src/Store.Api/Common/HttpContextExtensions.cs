using System.Text;
using Microsoft.AspNetCore.Http;

namespace Store.Api.Common;

/// <summary>
/// Request-context helpers used by auth handlers (correlation id, client IP,
/// user agent). Ported/condensed from haworks BuildingBlocks extensions.
/// </summary>
public static class HttpContextExtensions
{
    public const string CorrelationIdHeader = "X-Correlation-Id";

    /// <summary>
    /// Where a correlation id set by this service (rather than sent by the caller) is kept.
    /// </summary>
    private const string CorrelationIdItemKey = "Store.Api.CorrelationId";

    /// <summary>
    /// Where <c>Crux.Observability</c>'s own correlation-id middleware keeps the id for this
    /// request.
    /// </summary>
    /// <remarks>
    /// That middleware runs at the top of the pipeline (<c>Program.cs</c>,
    /// <c>app.UseCorrelationId()</c>). It reads the same header, and mints a GUID when the caller
    /// sent none. Reading it here is what makes one purchase carry ONE id.
    /// <para>
    /// Before this, a request with no inbound header got that GUID on every framework log line
    /// and on every outbound HTTP call, while this service put its trace id into the Stripe
    /// metadata and into the lines it ships to the central log. Two ids for one purchase, so
    /// grepping the id off a fulfilment line found nothing from the checkout that caused it,
    /// which is the entire point of carrying an id at all.
    /// </para>
    /// <para>
    /// The literal belongs to the package, not to us, so it can move without a compiler error.
    /// <c>CorrelationIdIsOneIdTests</c> drives the real pipeline and fails if it ever does.
    /// </para>
    /// </remarks>
    internal const string PackageCorrelationIdItemKey = "CorrelationId";

    /// <summary>
    /// The longest correlation id this service will carry.
    /// </summary>
    /// <remarks>
    /// This is a fence, not a formatting preference. The id is stamped onto the Stripe Checkout
    /// Session metadata so one string spans browser to delivery, and Stripe rejects a metadata
    /// VALUE over 500 characters by refusing to create the session. The header arrives from the
    /// buyer's browser, so without a cap anyone could send a 600-character
    /// <c>X-Correlation-Id</c> and turn our own tracing into a refusal to sell. 64 is far below
    /// Stripe's limit and far above a uuid.
    /// </remarks>
    private const int MaxCorrelationIdLength = 64;

    /// <summary>
    /// The id for this request: one set by this service, else the caller's header, else the
    /// framework's own trace id.
    /// </summary>
    /// <remarks>
    /// The header is sanitised, never returned raw. It is written into log lines, into Stripe
    /// metadata and into the fulfilment trail, so a hostile value gets to travel a long way. A
    /// newline would forge a second log line; a 10 KB value would break checkout. Anything
    /// outside <c>[A-Za-z0-9._-]</c> is dropped and the rest is truncated; if nothing usable
    /// survives, the framework's trace id is used, which is always well formed.
    /// </remarks>
    public static string GetCorrelationId(this HttpContext context)
    {
        if (context.Items.TryGetValue(CorrelationIdItemKey, out var stored)
            && stored is string set && set.Length > 0)
        {
            return set;
        }
        if (context.Items.TryGetValue(PackageCorrelationIdItemKey, out var fromPackage)
            && fromPackage is string raw && Sanitize(raw) is { Length: > 0 } shared)
        {
            return shared;
        }
        if (context.Request.Headers.TryGetValue(CorrelationIdHeader, out var value)
            && Sanitize(value.ToString()) is { Length: > 0 } clean)
        {
            return clean;
        }
        return context.TraceIdentifier;
    }

    /// <summary>
    /// Adopt an id that arrived by some route other than the header, for the rest of this request.
    /// </summary>
    /// <remarks>
    /// The webhook is why this exists. Stripe calls us on a fresh connection carrying none of the
    /// buyer's headers, so without this every fulfilment log line would be stamped with an
    /// unrelated trace id and the chain would break at exactly the step an operator most needs to
    /// follow. <c>WebhookEndpoints</c> reads the id back off the session metadata and sets it
    /// here, so every line logged after that point — including PAID-WITHOUT-FULFILMENT — carries
    /// the same string the browser started with.
    /// <para>
    /// Sanitised on the way in as well as on the way out: a value read back from a provider is
    /// no more trustworthy than one read off a header.
    /// </para>
    /// </remarks>
    public static void SetCorrelationId(this HttpContext context, string? correlationId)
    {
        if (Sanitize(correlationId) is { Length: > 0 } clean)
        {
            context.Items[CorrelationIdItemKey] = clean;
            // The package's key too, so the id we adopted also rides on outbound HTTP calls:
            // CorrelationIdHttpClientHandler reads that key at send time. Leaving it alone would
            // put the buyer's id in our log lines and the webhook's own GUID on every call this
            // request goes on to make.
            context.Items[PackageCorrelationIdItemKey] = clean;
        }
    }

    /// <summary>
    /// Keep <c>[A-Za-z0-9._-]</c>, drop the rest, truncate. Returns null when nothing survives.
    /// </summary>
    public static string? Sanitize(string? raw)
    {
        if (string.IsNullOrEmpty(raw)) return null;

        var kept = new StringBuilder(Math.Min(raw.Length, MaxCorrelationIdLength));
        foreach (var c in raw)
        {
            if (kept.Length == MaxCorrelationIdLength) break;
            var allowed = (c >= 'a' && c <= 'z')
                || (c >= 'A' && c <= 'Z')
                || (c >= '0' && c <= '9')
                || c == '.' || c == '_' || c == '-';
            if (allowed) kept.Append(c);
        }
        return kept.Length == 0 ? null : kept.ToString();
    }

    public static string GetClientIpAddress(this HttpContext context) =>
        context.Connection.RemoteIpAddress?.ToString() ?? "unknown";

    public static string GetUserAgent(this HttpContext context) =>
        context.Request.Headers.UserAgent.ToString() is { Length: > 0 } ua ? ua : "unknown";
}
