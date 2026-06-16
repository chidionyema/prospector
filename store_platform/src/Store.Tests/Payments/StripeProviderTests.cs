using System.Security.Cryptography;
using System.Text;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging.Abstractions;
using Store.Api.Payments;

namespace Store.Tests.Payments;

public sealed class StripeProviderTests
{
    private readonly IConfiguration _config;
    private readonly StripeProvider _provider;
    private const string Secret = "whsec_test";

    public StripeProviderTests()
    {
        _config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>(StringComparer.Ordinal)
            {
                ["Stripe:WebhookSecret"] = Secret,
                ["Stripe:ApiKey"] = "sk_test_123"
            })
            .Build();
        _provider = new StripeProvider(_config, NullLogger<StripeProvider>.Instance);
    }

    [Fact]
    public async Task VerifyAndParseAsync_ValidSignature_ReturnsTransaction()
    {
        // Stripe.net EventUtility.ConstructEvent uses HMACSHA256 for the signature.
        // We can manually construct a valid-looking signature for testing.
        var timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString(System.Globalization.CultureInfo.InvariantCulture);
        // Realistic Stripe event shape: must include top-level "object":"event" and
        // "request" (Stripe.net's EventConverter dereferences jsonObject["request"]) and
        // the inner "object":"checkout.session" discriminator so data.object types as Session.
        var body = "{\"id\":\"evt_123\",\"object\":\"event\",\"type\":\"checkout.session.completed\",\"request\":null,\"data\":{\"object\":{\"id\":\"cs_123\",\"object\":\"checkout.session\",\"payment_intent\":\"pi_123\",\"customer_details\":{\"email\":\"buyer@example.com\",\"address\":{\"country\":\"US\"}},\"amount_total\":3000,\"currency\":\"gbp\",\"metadata\":{\"pack_id\":\"pack-1\"}}},\"created\":1718553600}";
        
        var payload = $"{timestamp}.{body}";
        using var hmac = new HMACSHA256(Encoding.UTF8.GetBytes(Secret));
        var hash = Convert.ToHexStringLower(hmac.ComputeHash(Encoding.UTF8.GetBytes(payload)));
        var signature = $"t={timestamp},v1={hash}";

        var request = new DefaultHttpContext().Request;
        request.Headers["Stripe-Signature"] = signature;

        var result = await _provider.VerifyAndParseAsync(request, body, _config, NullLogger.Instance);

        Assert.True(result.Verified);
        Assert.NotNull(result.Transaction);
        Assert.Equal("pi_123", result.Transaction!.TransactionId);
        Assert.Equal("buyer@example.com", result.Transaction.BuyerEmail);
        Assert.Equal("stripe", result.Transaction.Provider);
        Assert.Single(result.Transaction.Items);
        Assert.Equal("pack-1", result.Transaction.Items[0].ProductId);
    }

    [Fact]
    public async Task VerifyAndParseAsync_InvalidSignature_ReturnsFalse()
    {
        var body = "{}";
        var request = new DefaultHttpContext().Request;
        request.Headers["Stripe-Signature"] = "t=123,v1=wrong";

        var result = await _provider.VerifyAndParseAsync(request, body, _config, NullLogger.Instance);

        Assert.False(result.Verified);
        Assert.Equal("invalid-signature", result.Reason);
    }
}
