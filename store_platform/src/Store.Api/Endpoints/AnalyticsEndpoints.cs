using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using Microsoft.EntityFrameworkCore;
using Store.Catalog.Domain;
using Store.Catalog.Persistence;

namespace Store.Api.Endpoints;

/// <summary>
/// First-party storefront analytics: an ingest endpoint the web app beacons to, and a
/// key-gated summary so baseline traffic can be read without shelling into the database.
///
/// Exists because the storefront had no measurement at all — no way to know visitors,
/// CTA click-through, or purchase rate, and therefore no way to size (or justify) any
/// copy/conversion experiment. Third-party tools were rejected: a script tag adds a consent
/// banner obligation and an external dependency for what is, at this stage, four counters.
/// </summary>
public static class AnalyticsEndpoints
{
    /// <summary>
    /// Server-side allowlist. Free-text event names would make the table an unbounded
    /// namespace anyone can spam; four known counters is the entire contract.
    /// </summary>
    private static readonly HashSet<string> AllowedNames = new(StringComparer.Ordinal)
    {
        "page_view",
        "sample_cta_clicked",
        "catalog_cta_clicked",
        "checkout_completed",
    };

    /// <summary>
    /// Beacon payload. Deliberately carries no visitor identifier — see AnalyticsEvent's
    /// remarks. An older storefront bundle also posted a "sessionId"; System.Text.Json skips
    /// unmapped members, so those beacons still succeed and the value is simply discarded.
    /// That is what makes web and API deployable in either order.
    /// </summary>
    public sealed record AnalyticsEventRequest(string? Name, string? Path, string? Meta);

    public static void MapAnalyticsEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapPost("/events", RecordAsync)
            .WithName("RecordAnalyticsEvent")
            .WithOpenApi();

        app.MapGet("/internal/analytics/summary", SummaryAsync)
            .WithName("AnalyticsSummary")
            .WithOpenApi();
    }

    private static async Task<IResult> RecordAsync(AnalyticsEventRequest request, StoreDbContext db)
    {
        if (string.IsNullOrEmpty(request.Name) || !AllowedNames.Contains(request.Name))
        {
            return Results.BadRequest(new { error = "unknown event name" });
        }

        db.AnalyticsEvents.Add(new AnalyticsEvent
        {
            Name = request.Name,
            // Truncate rather than reject: a beacon that 400s for length silently loses
            // the count, and the count is the whole point. Names are the strict part.
            Path = Truncate(request.Path, 256),
            Meta = Truncate(request.Meta, 512),
        });

        try
        {
            await db.SaveChangesAsync().ConfigureAwait(false);
        }
        catch (DbUpdateException)
        {
            // The (Name, Meta) unique index rejected a repeat of an event that carries an
            // order id — i.e. the buyer reloaded the success page. That is the dedup working,
            // not an error: the first beacon is already counted, so the caller has nothing to
            // fix and nothing to retry. Answering 202 keeps the beacon fire-and-forget.
            db.ChangeTracker.Clear();
            return Results.Accepted();
        }

        return Results.Accepted();
    }

    private static async Task<IResult> SummaryAsync(HttpRequest http, StoreDbContext db, IConfiguration config, int? days)
    {
        if (RejectUnlessInternal(http, config) is { } rejection)
        {
            return rejection;
        }

        var windowDays = days is null or <= 0 ? 14 : Math.Min(days.Value, 90);
        var since = DateTime.UtcNow.AddDays(-windowDays);

        // Group in memory: the filtered window is small (a few counters on a low-traffic
        // shop), and SQLite's date-part translation is not worth depending on for it.
        var rows = await db.AnalyticsEvents
            .Where(e => e.CreatedAt >= since)
            .Select(e => new { e.Name, e.CreatedAt })
            .ToListAsync()
            .ConfigureAwait(false);

        var byDay = rows
            .GroupBy(e => new { Day = e.CreatedAt.Date, e.Name })
            .OrderBy(g => g.Key.Day)
            .ThenBy(g => g.Key.Name, StringComparer.Ordinal)
            .Select(g => new
            {
                date = g.Key.Day.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture),
                name = g.Key.Name,
                count = g.Count(),
            })
            .ToList();

        var totals = rows
            .GroupBy(e => e.Name, StringComparer.Ordinal)
            .OrderBy(g => g.Key, StringComparer.Ordinal)
            .Select(g => new { name = g.Key, count = g.Count() })
            .ToList();

        return Results.Ok(new { days = windowDays, totals, byDay });
    }

    /// <summary>
    /// Same fail-closed key check as /internal/catalog: counts are low-sensitivity, but an
    /// open aggregate endpoint invites scraping our conversion numbers.
    /// </summary>
    private static IResult? RejectUnlessInternal(HttpRequest http, IConfiguration config)
    {
        var expectedKey = config["Store:InternalApiKey"]
            ?? Environment.GetEnvironmentVariable("STORE_INTERNAL_API_KEY");
        if (string.IsNullOrEmpty(expectedKey))
        {
            return Results.Problem("Internal API key not configured", statusCode: StatusCodes.Status503ServiceUnavailable);
        }
        var providedKey = http.Headers["X-Internal-Key"].ToString();
        if (string.IsNullOrEmpty(providedKey) ||
            !CryptographicOperations.FixedTimeEquals(
                Encoding.UTF8.GetBytes(providedKey),
                Encoding.UTF8.GetBytes(expectedKey)))
        {
            return Results.Unauthorized();
        }
        return null;
    }

    private static string? Truncate(string? value, int max) =>
        value is null || value.Length <= max ? value : value[..max];
}
