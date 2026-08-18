using System.Security.Cryptography;
using System.Text;
using Microsoft.EntityFrameworkCore;
using Store.Api.Payments;
using Store.Catalog.Persistence;

namespace Store.Api.Endpoints;

/// <summary>
/// Which registered packs are not on the shelf, and which gate is holding each one.
///
/// WHY THIS EXISTS. Founder, 2026-08-18: "why only 74 listed? u have blidspots". The shelf said
/// listed 74, registered 182 (GET /catalog/stats) and that was the whole of what the estate could
/// say. 108 packs were registered and not listed and NOTHING anywhere — not the API, not the ops
/// console, not a script — could name one of them or say why. GET /catalog/{id} 404s an unlisted
/// pack on purpose, GET /catalog returns listed rows only, and the publish path computes the
/// listing decision (Program.cs:668) rather than rejecting it, so a pack that fails a gate is
/// stored quietly and nothing errors.
///
/// A count with no reasons is not a measurement, it is a prompt to go and investigate by hand.
/// This endpoint turns "why only 74?" from an investigation into a request.
///
/// The reasons here are the SAME conditions the publish path applies, in the same order. If that
/// order changes, this changes with it, or the report becomes a plausible-looking lie.
/// PublishListingGateTests pins the gate; UnlistedReportTests pins this against it.
/// </summary>
public static class UnlistedEndpoints
{
    public static void MapUnlistedEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/internal/catalog/unlisted", GetUnlisted)
            .WithName("GetUnlistedPacks")
            .WithOpenApi();
    }

    // Same shared-key check as every other /internal endpoint, and FAIL CLOSED when no key is
    // configured. This lists titles of packs that are deliberately not public, including ones
    // withdrawn for a reason, so "no key configured" must never mean "no check".
    private static IResult? Reject(HttpRequest http, IConfiguration config)
    {
        var expectedKey = config["Store:InternalApiKey"]
            ?? Environment.GetEnvironmentVariable("STORE_INTERNAL_API_KEY");
        if (string.IsNullOrEmpty(expectedKey))
        {
            return Results.Problem("Internal API key not configured",
                statusCode: StatusCodes.Status503ServiceUnavailable);
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

    /// <param name="checkBilling">
    /// Probe the payment provider for each pack that clears every structural gate. OFF by default
    /// because it is one network call per pack against a live money rail, and a report you run to
    /// answer a question should not cost a hundred Stripe calls unless you asked for them. With it
    /// off those packs read `billing_unproven`, which is honest: this report never guesses.
    /// </param>
    private static async Task<IResult> GetUnlisted(
        HttpRequest http,
        StoreDbContext db,
        IConfiguration config,
        IServiceProvider sp,
        bool checkBilling = false)
    {
        var rejected = Reject(http, config);
        if (rejected is not null) return rejected;

        var ct = http.HttpContext?.RequestAborted ?? CancellationToken.None;

        // Hidden packs are excluded from BOTH numbers in /catalog/stats, so they are excluded
        // here too. A report whose total does not reconcile with the number the founder is
        // looking at is a second blind spot, not a fix for the first.
        var packs = await db.Packs
            .Where(p => !p.HiddenFromCatalogue)
            .OrderByDescending(p => p.CreatedAt)
            .ToListAsync(ct)
            .ConfigureAwait(false);

        var registered = packs.Count;
        var listed = packs.Count(p => p.IsListed);
        var hidden = await db.Packs.CountAsync(p => p.HiddenFromCatalogue, ct).ConfigureAwait(false);

        var rows = new List<object>();
        var byReason = new Dictionary<string, int>();

        foreach (var pack in packs.Where(p => !p.IsListed))
        {
            string reason;
            if (pack.DelistedAt is not null)
            {
                // Not a defect. Somebody withdrew this on purpose and said why.
                reason = "delisted";
            }
            else if (string.IsNullOrEmpty(pack.ContentKey))
            {
                // The first gate at Program.cs:668. This is the silent one: the publisher POSTs
                // IsListed=true, the pack has no deliverable, and `wantsListing` is computed to
                // false without an error anyone sees.
                reason = "no_content";
            }
            else if (sp.GetKeyedService<IPaymentProvider>(pack.PaymentProvider) is null)
            {
                reason = "no_payment_provider";
            }
            else if (string.IsNullOrEmpty(pack.ProviderPriceId))
            {
                reason = "no_price_id";
            }
            else if (!checkBilling)
            {
                reason = "billing_unproven";
            }
            else
            {
                var provider = sp.GetRequiredKeyedService<IPaymentProvider>(pack.PaymentProvider);
                var billable = await provider
                    .CanBillPriceAsync(pack.ProviderPriceId!, ct)
                    .ConfigureAwait(false);
                // Clears every gate this endpoint knows about and is still not listed. That is
                // either a pack nobody asked to list, or a gate that exists and is not modelled
                // here. Naming it `unexplained` rather than folding it into a neighbouring bucket
                // is the point: it is the number that says this report is incomplete.
                reason = billable ? "unexplained" : "unbillable_price";
            }

            byReason[reason] = byReason.GetValueOrDefault(reason) + 1;
            rows.Add(new
            {
                pack.Id,
                pack.Title,
                pack.CreatedAt,
                Reason = reason,
                HasContentKey = !string.IsNullOrEmpty(pack.ContentKey),
                pack.PaymentProvider,
                HasPriceId = !string.IsNullOrEmpty(pack.ProviderPriceId),
                pack.PricePence,
                pack.DelistReason,
                pack.Market,
            });
        }

        return Results.Ok(new
        {
            Registered = registered,
            Listed = listed,
            Unlisted = registered - listed,
            Hidden = hidden,
            BillingChecked = checkBilling,
            ByReason = byReason,
            Packs = rows,
        });
    }
}
