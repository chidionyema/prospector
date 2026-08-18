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
    /// namespace anyone can spam; a known set of counters is the entire contract.
    ///
    /// This list and <c>AnalyticsEventName</c> in <c>Store.Web/src/lib/analytics.ts</c> are two
    /// halves of one contract, and they had silently drifted: the storefront was emitting
    /// pack_shared, basket_removed, matchmaker_answered, palette_search and copy_variant from
    /// live call sites, every one of which 400d here and was counted nowhere. A dropped beacon
    /// looks identical to a visitor who never acted, so the drift reads as "nobody uses this
    /// feature" rather than as a bug. <c>AnalyticsNameContractTests</c> now pins the two lists
    /// together so the next addition cannot land on one side only.
    /// </summary>
    private static readonly HashSet<string> AllowedNames = new(StringComparer.Ordinal)
    {
        "page_view",
        "sample_cta_clicked",
        "catalog_cta_clicked",
        "checkout_completed",
        "pack_shared",
        "basket_removed",
        "matchmaker_answered",
        "palette_search",
        "copy_variant",
        // The pricing instrument (build plan D2). price_viewed is the denominator and
        // checkout_started the numerator of the only conversion rate that moves fast enough
        // to evaluate a ladder change; purchases are far too rare an event to learn from.
        "price_viewed",
        "checkout_started",
        // The title instrument. card_impression is the denominator and card_click the
        // numerator of catalogue click-through — the only signal fast enough to choose
        // between title forms, because one catalogue view is sixty-odd trials where a
        // purchase is one rare trial. card_impression carries a batch of pack ids, so its
        // Meta runs close to the 512-character truncation below by design; the client
        // chunks to fit (chunkCardIds in Store.Web/src/lib/analytics.ts).
        "card_impression",
        "card_click",
        // The FAQ helpfulness control (Store.Web/src/pages/faq.tsx). Meta is
        // "<question-slug>:up" or "<question-slug>:down" — keyed by the question text, not its
        // position, because the FAQ is ordered by purchase blocker and that order changes.
        "faq_helpful",
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

        app.MapGet("/internal/analytics/card-ctr", CardCtrAsync)
            .WithName("AnalyticsCardCtr")
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
    /// Per-pack catalogue click-through: impressions, clicks and the ratio, over a window.
    ///
    /// The instrument is useless without this. <c>SummaryAsync</c> groups by event name, so
    /// it can only ever say "8,000 impressions, 300 clicks" across the whole shelf — a number
    /// that cannot compare one title against another, which is the only question the events
    /// were added to answer. A counter nothing reads per-pack is a write-only loop.
    ///
    /// Impressions and clicks are counted per (session, pack) pair, not per beacon. A visitor
    /// who scrolls a card into view, navigates away and comes back has seen one card once for
    /// the purpose of judging its title; counting the second sighting would make a title look
    /// worse for the visitor's browsing habit. Ratios are the reason the client sends a
    /// session id at all.
    ///
    /// Malformed or truncated Meta is skipped rather than guessed at. A beacon cut by the 512
    /// limit is not partially recoverable, and inventing a pack id from half a JSON string
    /// would put fictional cards in the denominator.
    /// </summary>
    private static async Task<IResult> CardCtrAsync(HttpRequest http, StoreDbContext db, IConfiguration config, int? days)
    {
        if (RejectUnlessInternal(http, config) is { } rejection)
        {
            return rejection;
        }

        var windowDays = days is null or <= 0 ? 14 : Math.Min(days.Value, 90);
        var since = DateTime.UtcNow.AddDays(-windowDays);

        var rows = await db.AnalyticsEvents
            .Where(e => e.CreatedAt >= since
                && (e.Name == "card_impression" || e.Name == "card_click"))
            .Select(e => new { e.Name, e.Meta })
            .ToListAsync()
            .ConfigureAwait(false);

        var impressions = new HashSet<(string Session, string Pack)>();
        var clicks = new HashSet<(string Session, string Pack)>();
        var packs = new HashSet<string>(StringComparer.Ordinal);
        var skipped = 0;

        foreach (var row in rows)
        {
            if (!TryReadCardMeta(row.Meta, out var session, out var packIds))
            {
                skipped++;
                continue;
            }
            var isImpression = string.Equals(row.Name, "card_impression", StringComparison.Ordinal);
            var target = isImpression ? impressions : clicks;
            foreach (var pack in packIds)
            {
                packs.Add(pack);
                target.Add((session, pack));
            }
        }

        return Results.Ok(new
        {
            days = windowDays,
            packs = RankPacks(packs, impressions, clicks),
            // Surfaced rather than swallowed: a rising skip count means beacons are being
            // truncated or malformed, and every skipped row is a hole in the denominator.
            skipped_events = skipped,
        });
    }

    /// <summary>
    /// Turns the deduplicated (session, pack) pairs into one row per pack, busiest first.
    /// </summary>
    private static List<object> RankPacks(
        HashSet<string> packs,
        HashSet<(string Session, string Pack)> impressions,
        HashSet<(string Session, string Pack)> clicks) =>
        packs
            .Select(pack =>
            {
                var seen = impressions.Count(x => string.Equals(x.Pack, pack, StringComparison.Ordinal));
                var clicked = clicks.Count(x => string.Equals(x.Pack, pack, StringComparison.Ordinal));
                return new
                {
                    pack_id = pack,
                    impressions = seen,
                    clicks = clicked,
                    // Null, not zero, when nobody saw the card: a rate over no trials is
                    // undefined, and a zero would rank an unseen card as a proven failure.
                    ctr = seen == 0 ? (double?)null : Math.Round((double)clicked / seen, 4),
                };
            })
            .OrderByDescending(x => x.impressions)
            .ThenBy(x => x.pack_id, StringComparer.Ordinal)
            .Cast<object>()
            .ToList();

    /// <summary>
    /// Reads the client's card beacon shape: {"s":"session","p":["packId",...]} for a batch
    /// of impressions, or {"s":"session","p":"packId","i":0} for a single click.
    /// </summary>
    private static bool TryReadCardMeta(string? meta, out string session, out List<string> packIds)
    {
        session = string.Empty;
        packIds = [];
        if (string.IsNullOrWhiteSpace(meta))
        {
            return false;
        }

        try
        {
            using var doc = System.Text.Json.JsonDocument.Parse(meta);
            var root = doc.RootElement;
            if (root.ValueKind != System.Text.Json.JsonValueKind.Object)
            {
                return false;
            }

            // An empty session id is what the client sends when storage is unavailable.
            // Those beacons still count, but they cannot be joined, so they get a bucket of
            // their own rather than being merged into one fictional mega-visitor.
            session = root.TryGetProperty("s", out var s) && s.ValueKind == System.Text.Json.JsonValueKind.String
                ? (s.GetString() ?? string.Empty)
                : string.Empty;
            if (session.Length == 0)
            {
                session = Guid.NewGuid().ToString("N");
            }

            if (!root.TryGetProperty("p", out var p))
            {
                return false;
            }

            if (p.ValueKind == System.Text.Json.JsonValueKind.String)
            {
                var one = p.GetString();
                if (string.IsNullOrEmpty(one)) return false;
                packIds.Add(one);
                return true;
            }

            if (p.ValueKind == System.Text.Json.JsonValueKind.Array)
            {
                foreach (var item in p.EnumerateArray())
                {
                    if (item.ValueKind != System.Text.Json.JsonValueKind.String) continue;
                    var value = item.GetString();
                    if (!string.IsNullOrEmpty(value)) packIds.Add(value);
                }
                return packIds.Count > 0;
            }

            return false;
        }
        catch (System.Text.Json.JsonException)
        {
            // Truncated at the 512-character limit, most likely. Not recoverable.
            return false;
        }
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
