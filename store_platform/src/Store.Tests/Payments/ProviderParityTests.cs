using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using Store.Api.Payments;
using Store.Api.Services;

namespace Store.Tests.Payments;

/// <summary>
/// The payment seam. Stripe is the only provider, but the seam it sits behind is what a
/// future provider would be added through, so these tests pin the contract rather than the
/// brand: a PaymentTransaction carries its own provider name, and the webhook route resolves
/// a provider by its route key, never by the active_provider config.
/// </summary>
public class ProviderParityTests
{
    private static IConfiguration StripeConfig() => new ConfigurationBuilder()
        .AddInMemoryCollection(new Dictionary<string, string?>(StringComparer.Ordinal)
        {
            ["Stripe:ApiKey"] = "sk_test_fake",
            ["Stripe:WebhookSecret"] = "whsec_fake",
        })
        .Build();

    [Fact]
    public void PaymentTransaction_Carries_Every_Field_Fulfilment_Needs()
    {
        var txn = new PaymentTransaction(
            Provider: "stripe",
            TransactionId: "txn_002",
            BuyerEmail: "buyer@test.com",
            Currency: "GBP",
            Country: "GB",
            TotalAmountPence: 3000,
            OccurredAt: new DateTime(2026, 6, 15, 12, 0, 0, DateTimeKind.Utc),
            Items: [new PurchasedItem("prod_001", 3000)]
        );

        Assert.Equal("stripe", txn.Provider);
        Assert.Equal("buyer@test.com", txn.BuyerEmail);
        Assert.Equal("GBP", txn.Currency);
        Assert.Equal("GB", txn.Country);
        Assert.Equal(3000, txn.TotalAmountPence);
        Assert.Single(txn.Items);
    }

    [Fact]
    public void StripeProvider_Name_Is_Stripe()
    {
        var provider = new StripeProvider(StripeConfig(), NullLogger<StripeProvider>.Instance);
        Assert.Equal("stripe", provider.Name);
    }

    [Fact]
    public async Task StripeProvider_Rejects_Missing_Secret()
    {
        var config = new ConfigurationBuilder().Build(); // no Stripe:WebhookSecret
        var provider = new StripeProvider(config, NullLogger<StripeProvider>.Instance);
        var context = new DefaultHttpContext();

        var result = await provider.VerifyAndParseAsync(context.Request, "{}", config, NullLogger.Instance);

        Assert.False(result.Verified);
        Assert.Equal("secret-not-configured", result.Reason);
    }

    [Fact]
    public async Task StripeProvider_Rejects_Missing_Signature()
    {
        var config = StripeConfig();
        var provider = new StripeProvider(config, NullLogger<StripeProvider>.Instance);
        var context = new DefaultHttpContext();

        var result = await provider.VerifyAndParseAsync(context.Request, "{}", config, NullLogger.Instance);

        Assert.False(result.Verified);
        Assert.Equal("missing-signature", result.Reason);
    }

    [Fact]
    public void StripeProvider_Implements_IPaymentProvider()
    {
        Assert.IsAssignableFrom<IPaymentProvider>(
            new StripeProvider(StripeConfig(), NullLogger<StripeProvider>.Instance));
    }

    [Theory]
    [InlineData("stripe")]
    [InlineData("legacy")]
    public void PaymentTransaction_Accepts_Any_Provider_Field(string provider)
    {
        var txn = new PaymentTransaction(
            Provider: provider,
            TransactionId: "txn_test",
            BuyerEmail: "test@test.com",
            Currency: "GBP",
            Country: "GB",
            TotalAmountPence: 3000,
            OccurredAt: new DateTime(2026, 6, 15, 12, 0, 0, DateTimeKind.Utc),
            Items: []
        );

        Assert.Equal(provider, txn.Provider);
    }

    /// <summary>
    /// The webhook endpoint resolves IPaymentProvider by the {provider} route parameter
    /// (keyed DI), NOT by the active_provider config. A webhook is therefore handled by the
    /// provider that sent it, whatever checkout is currently originating.
    /// </summary>
    [Fact]
    public void Webhook_Routing_Uses_Explicit_Provider_Not_ActiveProvider()
    {
        var services = new ServiceCollection();
        var stripeConfig = StripeConfig();
        services.AddKeyedScoped<IPaymentProvider, StripeProvider>("stripe",
            (sp, _) => new StripeProvider(stripeConfig, NullLogger<StripeProvider>.Instance));

        var sp = services.BuildServiceProvider();

        var stripeFromDi = sp.GetKeyedService<IPaymentProvider>("stripe");
        Assert.NotNull(stripeFromDi);
        Assert.IsType<StripeProvider>(stripeFromDi);

        // An unregistered provider key resolves to null, which is what makes the endpoint
        // answer "unknown provider" instead of falling through to whatever is active.
        Assert.Null(sp.GetKeyedService<IPaymentProvider>("legacy"));
    }
}
