using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging.Abstractions;
using Store.Api.Payments;

namespace Store.Tests.Payments;

public sealed class PaddleProviderTests
{
    private readonly IConfiguration _config;
    private readonly PaddleProvider _provider = new();
    private const string Secret = "test_secret";

    public PaddleProviderTests()
    {
        _config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>(StringComparer.Ordinal)
            {
                ["Paddle:WebhookSecret"] = Secret
            })
            .Build();
    }

    [Fact]
    public async Task VerifyAndParseAsync_ValidSignature_ReturnsTransaction()
    {
        var ts = DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString(CultureInfo.InvariantCulture);
        var body = "{\"event_type\":\"transaction.completed\",\"data\":{\"id\":\"txn_1\",\"currency_code\":\"USD\",\"customer_email\":\"test@example.com\",\"details\":{\"totals\":{\"total\":\"1000\"},\"line_items\":[{\"product_id\":\"prod_1\",\"totals\":{\"total\":\"1000\"}}]}},\"occurred_at\":\"2026-01-01T00:00:00Z\"}";
        
        var payload = $"{ts}:{body}";
        using var hmac = new HMACSHA256(Encoding.UTF8.GetBytes(Secret));
        var hash = Convert.ToHexStringLower(hmac.ComputeHash(Encoding.UTF8.GetBytes(payload)));
        var signature = $"ts={ts};h1={hash}";

        var request = new DefaultHttpContext().Request;
        request.Headers["Paddle-Signature"] = signature;

        var result = await _provider.VerifyAndParseAsync(request, body, _config, NullLogger.Instance);

        Assert.True(result.Verified);
        Assert.NotNull(result.Transaction);
        Assert.Equal("txn_1", result.Transaction!.TransactionId);
        Assert.Equal("test@example.com", result.Transaction.BuyerEmail);
        Assert.Equal("paddle", result.Transaction.Provider);
    }

    [Fact]
    public async Task VerifyAndParseAsync_InvalidSignature_ReturnsFalse()
    {
        var body = "{}";
        var request = new DefaultHttpContext().Request;
        request.Headers["Paddle-Signature"] = "ts=123;h1=wrong";

        var result = await _provider.VerifyAndParseAsync(request, body, _config, NullLogger.Instance);

        Assert.False(result.Verified);
        Assert.Equal("invalid-signature", result.Reason);
    }

    [Fact]
    public async Task VerifyAndParseAsync_IgnoredEventType_ReturnsIgnored()
    {
        var ts = DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString(CultureInfo.InvariantCulture);
        var body = "{\"event_type\":\"subscription.created\"}";
        
        var payload = $"{ts}:{body}";
        using var hmac = new HMACSHA256(Encoding.UTF8.GetBytes(Secret));
        var hash = Convert.ToHexStringLower(hmac.ComputeHash(Encoding.UTF8.GetBytes(payload)));
        var signature = $"ts={ts};h1={hash}";

        var request = new DefaultHttpContext().Request;
        request.Headers["Paddle-Signature"] = signature;

        var result = await _provider.VerifyAndParseAsync(request, body, _config, NullLogger.Instance);

        Assert.False(result.Verified);
        Assert.True(result.Ignored);
        Assert.Equal("subscription.created", result.Reason);
    }
}
