using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Store.Catalog.Domain;
using Store.Catalog.Persistence;

namespace Store.Api.Endpoints;

public static class WebhookEndpoints
{
    public static void MapWebhookEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapPost("/webhooks/paddle", HandlePaddleWebhook);
    }

    private static async Task<IResult> HandlePaddleWebhook(HttpRequest request, StoreDbContext db, IConfiguration config, ILogger<Program> logger)
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

        return await ProcessWebhookPayload(rawBody, db, logger).ConfigureAwait(false);
    }

    private static async Task<IResult> ProcessWebhookPayload(string rawBody, StoreDbContext db, ILogger logger)
    {
        try
        {
            using var jsonDoc = JsonDocument.Parse(rawBody);
            var root = jsonDoc.RootElement;
            var eventType = root.GetProperty("event_type").GetString();

            if (string.Equals(eventType, "transaction.completed", StringComparison.Ordinal))
            {
                return await HandleTransactionCompleted(root.GetProperty("data"), db, logger).ConfigureAwait(false);
            }

            return Results.Ok(new { status = "IGNORED", eventType });
        }
        catch (JsonException ex)
        {
            logger.LogError(ex, "Malformed Paddle webhook body.");
            return Results.BadRequest("Malformed body");
        }
    }

    private static async Task<IResult> HandleTransactionCompleted(JsonElement data, StoreDbContext db, ILogger logger)
    {
        var transactionId = data.GetProperty("id").GetString();
        
        if (await db.SalesAudits.AnyAsync(s => s.PaddleTransactionId == transactionId).ConfigureAwait(false))
        {
            return Results.Ok(new { status = "ALREADY_PROCESSED" });
        }

        var items = data.GetProperty("items");
        if (items.GetArrayLength() == 0) return Results.Ok(new { status = "NO_ITEMS" });

        var productId = items[0].GetProperty("price").GetProperty("product_id").GetString();
        var totals = data.GetProperty("details").GetProperty("totals");

        var audit = new SalesAudit
        {
            PaddleTransactionId = transactionId!,
            PaddleProductId = productId!,
            AmountPence = totals.GetProperty("total").GetInt64(),
            Currency = data.GetProperty("currency_code").GetString()!,
            Country = data.GetProperty("address").GetProperty("country_code").GetString()!,
            OccurredAt = DateTime.Parse(data.GetProperty("occurred_at").GetString()!, CultureInfo.InvariantCulture)
        };

        db.SalesAudits.Add(audit);
        await db.SaveChangesAsync().ConfigureAwait(false);
        
        logger.LogInformation("Processed sale for {ProductId}, Transaction: {TransactionId}", productId, transactionId);
        return Results.Ok(new { status = "PROCESSED" });
    }

    private static bool VerifyPaddleSignature(string signatureHeader, string rawBody, string secret)
    {
        var parts = signatureHeader.Split(';');
        var ts = Array.Find(parts, p => p.StartsWith("ts=", StringComparison.Ordinal))?.Split('=')[1];
        var h1 = Array.Find(parts, p => p.StartsWith("h1=", StringComparison.Ordinal))?.Split('=')[1];

        if (string.IsNullOrEmpty(ts) || string.IsNullOrEmpty(h1)) return false;

        if (!long.TryParse(ts, NumberStyles.Integer, CultureInfo.InvariantCulture, out var tsUnix)) return false;
        var offset = DateTimeOffset.FromUnixTimeSeconds(tsUnix);
        if (Math.Abs((DateTimeOffset.UtcNow - offset).TotalMinutes) > 5) return false;

        var payload = $"{ts}:{rawBody}";
        using var hmac = new HMACSHA256(Encoding.UTF8.GetBytes(secret));
        var hash = hmac.ComputeHash(Encoding.UTF8.GetBytes(payload));
        var hashString = Convert.ToHexStringLower(hash);

        return CryptographicOperations.FixedTimeEquals(
            Encoding.UTF8.GetBytes(hashString),
            Encoding.UTF8.GetBytes(h1));
    }
}
