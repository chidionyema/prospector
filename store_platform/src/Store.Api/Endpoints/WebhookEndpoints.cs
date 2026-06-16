using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Store.Api.Services;
using Store.Catalog.Domain;
using Store.Catalog.Persistence;

namespace Store.Api.Endpoints;

public static class WebhookEndpoints
{
    private const int SignatureToleranceMinutes = 5;

    public static void MapWebhookEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapPost("/webhooks/paddle", HandlePaddleWebhook);
    }

    private static async Task<IResult> HandlePaddleWebhook(
        HttpRequest request,
        IConfiguration config,
        ILogger<Program> logger,
        FulfilmentService fulfilmentService,
        StoreDbContext db,
        IEmailSender emailSender)
    {
        var secret = config["Paddle:WebhookSecret"];
        if (string.IsNullOrEmpty(secret))
        {
            logger.LogError("Paddle webhook secret is not configured. Failing closed.");
            return Results.StatusCode(StatusCodes.Status503ServiceUnavailable);
        }

        if (!request.Headers.TryGetValue("Paddle-Signature", out var signatureHeader))
        {
            logger.LogWarning("Paddle webhook missing signature header.");
            return Results.BadRequest("Missing signature");
        }

        using var reader = new StreamReader(request.Body);
        var rawBody = await reader.ReadToEndAsync().ConfigureAwait(false);

        if (!VerifyPaddleSignature(signatureHeader!, rawBody, secret))
        {
            logger.LogWarning("Paddle webhook signature verification failed.");
            return Results.BadRequest("Invalid signature");
        }

        var storeUrl = config["Store:PublicUrl"] ?? Environment.GetEnvironmentVariable("STORE_PUBLIC_URL");
        return await ProcessAsync(rawBody, fulfilmentService, db, emailSender, storeUrl, logger)
            .ConfigureAwait(false);
    }

    private static async Task<IResult> ProcessAsync(
        string rawBody,
        FulfilmentService fulfilmentService,
        StoreDbContext db,
        IEmailSender emailSender,
        string? storeUrl,
        ILogger logger)
    {
        PaddleTransaction txn;
        try
        {
            using var jsonDoc = JsonDocument.Parse(rawBody);
            var root = jsonDoc.RootElement;
            var eventType = OptionalString(root, "event_type");
            if (!string.Equals(eventType, "transaction.completed", StringComparison.Ordinal))
            {
                return Results.Ok(new { status = "IGNORED", eventType });
            }

            txn = ParsePaddleTransaction(root);
        }
        catch (JsonException ex)
        {
            logger.LogError(ex, "Malformed Paddle webhook body.");
            return Results.BadRequest("Malformed body");
        }

        // Fulfil: SalesAudit + Order(s) + Entitlement(s) in one atomic write. Idempotent.
        var outcome = await fulfilmentService.FulfilAsync(txn).ConfigureAwait(false);

        if (outcome.AlreadyProcessed)
        {
            return Results.Ok(new { status = "ALREADY_PROCESSED" });
        }

        if (outcome.Unfulfilled.Count > 0)
        {
            // Paid but undeliverable — an operator must reconcile. The money is recorded.
            logger.LogError("PAID-WITHOUT-FULFILMENT for {TransactionId}: {Items}",
                txn.TransactionId, string.Join(", ", outcome.Unfulfilled));
        }

        // Deliver the magic link AFTER the atomic write commits. A failed/skipped send is
        // non-fatal: the entitlement exists and the link is re-issuable.
        await DispatchEmailsAsync(outcome.EntitlementsCreated, db, emailSender, storeUrl, logger)
            .ConfigureAwait(false);

        return Results.Ok(new
        {
            status = "PROCESSED",
            entitlements = outcome.EntitlementsCreated.Count,
            unfulfilled = outcome.Unfulfilled,
        });
    }

    private static async Task DispatchEmailsAsync(
        IReadOnlyList<Entitlement> entitlements,
        StoreDbContext db,
        IEmailSender emailSender,
        string? storeUrl,
        ILogger logger)
    {
        if (entitlements.Count == 0 || string.IsNullOrEmpty(storeUrl) || !emailSender.IsConfigured)
        {
            return;
        }

        var baseUrl = storeUrl.TrimEnd('/');
        foreach (var ent in entitlements)
        {
            var title = await db.Packs
                .Where(p => p.Id == ent.PackId)
                .Select(p => p.Title)
                .FirstOrDefaultAsync()
                .ConfigureAwait(false) ?? ent.PackId;

            var orderUrl = $"{baseUrl}/orders/{ent.GrantToken}";
            var sent = await emailSender.SendDownloadLinkAsync(ent.BuyerEmail, title, orderUrl)
                .ConfigureAwait(false);
            if (!sent)
            {
                logger.LogWarning(
                    "Magic-link email not sent for {PackId} to {Email}; link can be re-issued.",
                    ent.PackId, ent.BuyerEmail);
            }
        }
    }

    private static PaddleTransaction ParsePaddleTransaction(JsonElement root)
    {
        var data = root.GetProperty("data");
        var details = data.GetProperty("details");
        var totals = details.GetProperty("totals");

        var items = new List<PurchasedItem>();
        if (details.TryGetProperty("line_items", out var lineItems)
            && lineItems.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in lineItems.EnumerateArray())
            {
                var productId = OptionalString(item, "product_id");
                var amount = item.TryGetProperty("totals", out var itemTotals)
                    ? ParseAmount(itemTotals, "total")
                    : 0;
                items.Add(new PurchasedItem(productId, amount));
            }
        }

        return new PaddleTransaction(
            TransactionId: OptionalString(data, "id") ?? "",
            BuyerEmail: ExtractEmail(data),
            Currency: OptionalString(data, "currency_code") ?? "GBP",
            Country: ExtractCountry(data),
            TotalAmountPence: ParseAmount(totals, "total"),
            OccurredAt: ParseOccurredAt(root),
            Items: items);
    }

    private static string ExtractEmail(JsonElement data)
    {
        if (data.TryGetProperty("custom_data", out var custom)
            && custom.ValueKind == JsonValueKind.Object
            && custom.TryGetProperty("email", out var customEmail))
        {
            return customEmail.GetString() ?? "";
        }

        return OptionalString(data, "customer_email") ?? "";
    }

    private static string ExtractCountry(JsonElement data) =>
        data.TryGetProperty("address", out var address) && address.ValueKind == JsonValueKind.Object
            ? OptionalString(address, "country_code") ?? ""
            : "";

    private static DateTime ParseOccurredAt(JsonElement root)
    {
        // Paddle puts occurred_at on the event envelope; fall back to data then to now.
        var raw = OptionalString(root, "occurred_at")
            ?? OptionalString(root.GetProperty("data"), "occurred_at");
        return raw is null
            ? DateTime.UtcNow
            : DateTime.Parse(raw, CultureInfo.InvariantCulture,
                DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal);
    }

    // Paddle sends monetary amounts as strings in the currency's smallest unit; tolerate
    // both string and number forms so a real webhook never throws on the money field.
    private static long ParseAmount(JsonElement parent, string name)
    {
        if (!parent.TryGetProperty(name, out var el))
        {
            return 0;
        }

        return el.ValueKind == JsonValueKind.String
            ? long.Parse(el.GetString()!, CultureInfo.InvariantCulture)
            : el.GetInt64();
    }

    private static string? OptionalString(JsonElement parent, string name) =>
        parent.TryGetProperty(name, out var el) ? el.GetString() : null;

    private static bool VerifyPaddleSignature(string signatureHeader, string rawBody, string secret)
    {
        var parts = signatureHeader.Split(';');
        var ts = Array.Find(parts, p => p.StartsWith("ts=", StringComparison.Ordinal))?.Split('=')[1];
        var h1 = Array.Find(parts, p => p.StartsWith("h1=", StringComparison.Ordinal))?.Split('=')[1];

        if (string.IsNullOrEmpty(ts) || string.IsNullOrEmpty(h1))
        {
            return false;
        }

        if (!long.TryParse(ts, NumberStyles.Integer, CultureInfo.InvariantCulture, out var tsUnix))
        {
            return false;
        }

        var offset = DateTimeOffset.FromUnixTimeSeconds(tsUnix);
        if (Math.Abs((DateTimeOffset.UtcNow - offset).TotalMinutes) > SignatureToleranceMinutes)
        {
            return false;
        }

        var payload = $"{ts}:{rawBody}";
        using var hmac = new HMACSHA256(Encoding.UTF8.GetBytes(secret));
        var hash = hmac.ComputeHash(Encoding.UTF8.GetBytes(payload));
        var hashString = Convert.ToHexStringLower(hash);

        return CryptographicOperations.FixedTimeEquals(
            Encoding.UTF8.GetBytes(hashString),
            Encoding.UTF8.GetBytes(h1));
    }
}
