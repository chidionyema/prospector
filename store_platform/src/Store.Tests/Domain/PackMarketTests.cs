using Store.Api.Contracts;
using Store.Catalog.Domain;

namespace Store.Tests.Domain;

/// <summary>
/// Market is the jurisdiction of the OPPORTUNITY, not the buyer's locale (Epic D).
/// These tests pin the boundary: the facet is additive and optional, and it must never
/// become a pricing input — the store sells every pack in GBP through the same rail.
/// </summary>
public class PackMarketTests
{
    private static Pack NewPack() => new()
    {
        Id = "p1",
        Title = "T",
        OneLine = "O",
        DossierRef = "d1",
        PricePence = 4900,
    };

    [Fact]
    public void Market_DefaultsToNull_SoPacksPublishedBeforeEpicDStayValid()
    {
        Assert.Null(NewPack().Market);
    }

    [Fact]
    public void PublishRequest_OmittingMarket_IsValid()
    {
        var request = new PublishRequest("p1", "T", "O", "d1");
        Assert.Null(request.Market);
    }

    [Theory]
    [InlineData("uk")]
    [InlineData("us")]
    [InlineData("us-tx")]
    public void Market_AcceptsHierarchicalCodes(string code)
    {
        var pack = NewPack();
        pack.Market = code;
        Assert.Equal(code, pack.Market);
    }

    [Fact]
    public void Market_DoesNotAffectPrice()
    {
        // The opportunity-market != buyer-market invariant: a US-market pack is still
        // £49 through the existing Stripe rail. If this ever needs to change it is a
        // deliberate currency project, not a side effect of opening a market.
        var pack = NewPack();
        pack.Market = "us";
        Assert.Equal(4900, pack.PricePence);
        Assert.Equal("£49.00", Money.ToDisplayString(pack.PricePence, "£"));
    }
}
