using System.Threading.RateLimiting;
using Microsoft.AspNetCore.Http;

namespace Store.Api.Infrastructure;

/// <summary>
/// The global rate-limit partitioning, extracted from Program.cs so the policy itself can be
/// exercised in a test rather than only asserted about in prose.
///
/// Three partitions, in priority order:
///
/// 1. <c>/webhooks</c> — <b>no limiter at all</b>. Payment providers retry on non-2xx, and a
///    429'd webhook drops a fulfilment for a customer who has already been charged. Throttling
///    the money rail to protect the money rail is the wrong trade.
/// 2. <c>/catalog/waitlist</c> — a much tighter budget, because it is the only unauthenticated
///    endpoint that writes a personal data row. Its own partition key prefix keeps that budget
///    separate from ordinary browsing, in both directions.
/// 3. everything else — the default per-IP browse budget.
/// </summary>
public static class RateLimitPolicy
{
    /// <summary>Requests per minute per IP for ordinary traffic when unconfigured.</summary>
    public const int DefaultPermitPerMinute = 120;

    /// <summary>Requests per minute per IP for the waitlist write when unconfigured.</summary>
    public const int DefaultWaitlistPermitPerMinute = 5;

    public const string WebhooksPathPrefix = "/webhooks";
    public const string WaitlistPath = "/catalog/waitlist";

    /// <summary>
    /// Build the partitioned limiter used as the global limiter. Taking the two permit values
    /// as parameters keeps configuration reading in Program.cs and leaves this pure enough to
    /// test with a hand-built <see cref="HttpContext"/>.
    /// </summary>
    public static PartitionedRateLimiter<HttpContext> Create(int permitPerMinute, int waitlistPermitPerMinute)
        => PartitionedRateLimiter.Create<HttpContext, string>(httpContext =>
        {
            var path = httpContext.Request.Path.Value ?? string.Empty;
            if (path.StartsWith(WebhooksPathPrefix, StringComparison.OrdinalIgnoreCase))
            {
                return RateLimitPartition.GetNoLimiter("webhooks");
            }

            var clientKey = httpContext.Connection.RemoteIpAddress?.ToString() ?? "unknown";

            if (path.StartsWith(WaitlistPath, StringComparison.OrdinalIgnoreCase))
            {
                return RateLimitPartition.GetFixedWindowLimiter(
                    $"waitlist:{clientKey}",
                    _ => new FixedWindowRateLimiterOptions
                    {
                        PermitLimit = waitlistPermitPerMinute,
                        Window = TimeSpan.FromMinutes(1),
                        QueueLimit = 0,
                    });
            }

            return RateLimitPartition.GetFixedWindowLimiter(
                clientKey,
                _ => new FixedWindowRateLimiterOptions
                {
                    PermitLimit = permitPerMinute,
                    Window = TimeSpan.FromMinutes(1),
                    QueueLimit = 0,
                });
        });
}
