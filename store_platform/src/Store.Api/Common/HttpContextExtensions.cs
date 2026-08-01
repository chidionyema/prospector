using Microsoft.AspNetCore.Http;

namespace Store.Api.Common;

/// <summary>
/// Request-context helpers used by auth handlers (correlation id, client IP,
/// user agent). Ported/condensed from haworks BuildingBlocks extensions.
/// </summary>
public static class HttpContextExtensions
{
    public const string CorrelationIdHeader = "X-Correlation-Id";

    public static string GetCorrelationId(this HttpContext context)
    {
        if (context.Request.Headers.TryGetValue(CorrelationIdHeader, out var value) && !string.IsNullOrEmpty(value))
            return value!;
        return context.TraceIdentifier;
    }

    public static string GetClientIpAddress(this HttpContext context) =>
        context.Connection.RemoteIpAddress?.ToString() ?? "unknown";

    public static string GetUserAgent(this HttpContext context) =>
        context.Request.Headers.UserAgent.ToString() is { Length: > 0 } ua ? ua : "unknown";
}
