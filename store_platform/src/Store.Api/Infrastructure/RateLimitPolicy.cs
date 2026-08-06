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
///
/// <b>Known blind spot — the storefront is not "an IP" (measured 2026-08-06).</b> The partition key
/// below is the client IP, which is the real visitor only for requests the browser makes directly.
/// Every server-rendered page instead reaches this API as a fresh connection from the storefront's
/// own egress, carrying no <c>X-Forwarded-For</c> of its own, so ALL SSR traffic for the whole site
/// shares ONE partition. A pack page costs two calls (<c>fetchPackDetails</c> + <c>fetchCatalog</c>,
/// Store.Web pages/pack/[id].tsx:1083-1086), so at the 120 default the storefront begins throttling
/// itself at roughly 60 page views a minute — and the visitor is served a 503 error page, because
/// pages/pack/[id].tsx:1112-1118 maps any non-404/410 to <c>res.statusCode = 503</c>.
///
/// This was found as an intermittent red live smoke: the last three tests of a 28-test sequential
/// run exhausted the shared budget and got 429, which the storefront rendered as 503 where the test
/// expected a 404 for a withdrawn pack. Fly logs, prospector-store-web, 13:53:56-58Z:
/// <c>Error fetching pack details: Error [ApiError] ... status: 429</c>.
///
/// Mitigated in production by raising the budget, NOT by fixing the partitioning:
/// <c>RateLimiting__PermitPerMinute=600</c> is set as a Fly secret on prospector-store-api
/// (2026-08-06), which moves the self-throttling ceiling to roughly 300 page views a minute. The
/// structural fix — have the storefront forward the visitor IP on server-side fetches and partition
/// on that, trusting the header only from the storefront — is NOT done. Until it is, the ceiling is
/// site-wide rather than per-visitor, and raising the number is the only lever.
/// </summary>
public static class RateLimitPolicy
{
    /// <summary>
    /// Requests per minute per IP for ordinary traffic when unconfigured. Production overrides this
    /// via <c>RateLimiting__PermitPerMinute</c>; see the blind-spot note above before lowering it,
    /// because this budget is shared by all server-rendered traffic, not spent per visitor.
    /// </summary>
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
