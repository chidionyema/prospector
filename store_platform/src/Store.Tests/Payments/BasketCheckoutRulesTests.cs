using Microsoft.Extensions.Configuration;
using Store.Api.Endpoints;
using Store.Api.Payments;
using Store.Catalog.Domain;

namespace Store.Tests.Payments;

/// <summary>
/// The rules POST /checkout applies to a basket before any money moves.
/// </summary>
public sealed class BasketCheckoutRulesTests
{
    [Fact]
    public void ValidateBasket_AcceptsOnePack()
    {
        // A basket of one is not a special case — it is the path /packs/{id}/checkout now takes.
        Assert.Null(CheckoutEndpoints.ValidateBasket(["pack-1"]));
    }

    [Fact]
    public void ValidateBasket_AcceptsUpToTheLineCap()
    {
        var full = Enumerable.Range(0, StripeProvider.MaxCheckoutLines).Select(i => $"pack-{i}").ToArray();
        Assert.Null(CheckoutEndpoints.ValidateBasket(full));
    }

    [Fact]
    public void ValidateBasket_RejectsEmpty()
    {
        Assert.NotNull(CheckoutEndpoints.ValidateBasket([]));
    }

    [Fact]
    public void ValidateBasket_RejectsOverTheLineCap()
    {
        // Over the cap the provider session would be rejected by Stripe for metadata length —
        // answer here instead, where the message can say what happened.
        var overflowing = Enumerable.Range(0, StripeProvider.MaxCheckoutLines + 1)
            .Select(i => $"pack-{i}").ToArray();

        Assert.NotNull(CheckoutEndpoints.ValidateBasket(overflowing));
    }

    [Fact]
    public void ValidateBasket_RejectsDuplicates()
    {
        // Collapsing the duplicate would charge £49 to a buyer who thought they were buying two,
        // and granting twice is meaningless for a one-off download. Neither is an answer.
        Assert.NotNull(CheckoutEndpoints.ValidateBasket(["pack-1", "pack-2", "pack-1"]));
    }

    [Fact]
    public void ValidateBasket_RejectsBlankIds()
    {
        Assert.NotNull(CheckoutEndpoints.ValidateBasket(["pack-1", "   "]));
    }

    [Fact]
    public void ResolveProviderName_RuntimeActiveProviderWins()
    {
        // P7 — the hot-switch config decides for new checkouts, whatever the packs were
        // published against.
        var name = CheckoutEndpoints.ResolveProviderName(
            ConfigWith("stripe"),
            [PackOn("paddle"), PackOn("paddle")]);

        Assert.Equal("stripe", name);
    }

    [Fact]
    public void ResolveProviderName_FallsBackToTheStoredProvider()
    {
        Assert.Equal("paddle", CheckoutEndpoints.ResolveProviderName(ConfigWith(null), [PackOn("paddle")]));
    }

    [Fact]
    public void ResolveProviderName_MixedProvidersWithNoRuntimeOverride_IsUnresolvable()
    {
        // One transaction cannot be billed through two providers. Null makes the endpoint answer
        // 409 rather than silently charging everything through whichever pack came first.
        Assert.Null(CheckoutEndpoints.ResolveProviderName(
            ConfigWith(null),
            [PackOn("stripe"), PackOn("paddle")]));
    }

    private static IConfiguration ConfigWith(string? activeProvider) =>
        new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>(StringComparer.Ordinal)
            {
                ["payments:active_provider"] = activeProvider,
            })
            .Build();

    private static Pack PackOn(string provider) => new()
    {
        Id = Guid.NewGuid().ToString("N"),
        Title = "Test pack",
        OneLine = "A test pack.",
        DossierRef = "dossier-ref",
        PricePence = 4900,
        PaymentProvider = provider,
    };
}
