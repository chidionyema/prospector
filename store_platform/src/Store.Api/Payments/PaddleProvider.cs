using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Store.Api.Services;

namespace Store.Api.Payments;

public sealed class PaddleProvider : IPaymentProvider
{
    private const int SignatureToleranceMinutes = 5;

    public string Name => "paddle";

    public Task<WebhookVerifyResult> VerifyAndParseAsync(HttpRequest request, string rawBody, IConfiguration config, ILogger logger)
    {
        var secret = config["Paddle:WebhookSecret"];
        if (string.IsNullOrEmpty(secret))
        {
            logger.LogError("Paddle webhook secret is not configured. Failing closed.");
            return Task.FromResult(new WebhookVerifyResult(false, null, "secret-not-configured"));
        }

        if (!request.Headers.TryGetValue("Paddle-Signature", out var signatureHeader))
        {
            logger.LogWarning("Paddle webhook missing signature header.");
            return Task.FromResult(new WebhookVerifyResult(false, null, "missing-signature"));
        }

        if (!VerifyPaddleSignature(signatureHeader!, rawBody, secret))
        {
            logger.LogWarning("Paddle webhook signature verification failed.");
            return Task.FromResult(new WebhookVerifyResult(false, null, "invalid-signature"));
        }

        try
        {
            using var jsonDoc = JsonDocument.Parse(rawBody);
            var root = jsonDoc.RootElement;
            var eventType = OptionalString(root, "event_type");
            if (!string.Equals(eventType, "transaction.completed", StringComparison.Ordinal))
            {
                return Task.FromResult(new WebhookVerifyResult(false, null, eventType, Ignored: true));
            }

            var txn = ParsePaddleTransaction(root);
            return Task.FromResult(new WebhookVerifyResult(true, txn, null));
        }
        catch (JsonException ex)
        {
            logger.LogError(ex, "Malformed Paddle webhook body.");
            return Task.FromResult(new WebhookVerifyResult(false, null, "malformed"));
        }
    }

    public Task<ProviderProduct> CreateProductAsync(string title, long pricePence, string currency, IDictionary<string, string> metadata, CancellationToken ct)
    {
        throw new NotSupportedException("Paddle provisioning is handled by the Python bridge; Paddle checkout is a frontend overlay.");
    }

    public Task<CheckoutHandle> CreateCheckoutAsync(string providerPriceId, string? buyerEmail, string successUrl, string cancelUrl, CancellationToken ct)
    {
        throw new NotSupportedException("Paddle provisioning is handled by the Python bridge; Paddle checkout is a frontend overlay.");
    }

    private static PaymentTransaction ParsePaddleTransaction(JsonElement root)
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

        return new PaymentTransaction(
            Provider: "paddle",
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
        var raw = OptionalString(root, "occurred_at")
            ?? OptionalString(root.GetProperty("data"), "occurred_at");
        return raw is null
            ? DateTime.UtcNow
            : DateTime.Parse(raw, CultureInfo.InvariantCulture,
                DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal);
    }

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
