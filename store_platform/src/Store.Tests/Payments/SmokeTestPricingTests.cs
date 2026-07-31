namespace Store.Tests.Payments;

using Store.Api.Payments;
using Xunit;

/// <summary>
/// The override lowers a live price, so these tests are about what must NOT happen far more than
/// what must. Every case here is a way a buyer could otherwise pay 50p for a £49 pack, or a way
/// the founder could be billed £49 while believing the test price applied.
/// </summary>
public class SmokeTestPricingTests
{
    private const string RealKey = "internal-key-abcdefghijklmnop";
    private const string SmokePrice = "price_smoke_50p";

    private static readonly CheckoutLine[] Lines =
    [
        new("pack-a", "price_real_a"),
        new("pack-b", "price_real_b"),
    ];

    [Fact]
    public void an_ordinary_buyer_sending_no_header_pays_the_listed_price()
    {
        var r = SmokeTestPricing.Evaluate(Lines, null, RealKey, SmokePrice);

        Assert.Equal(SmokeTestPricing.Outcome.NotRequested, r.Outcome);
        Assert.Equal(["price_real_a", "price_real_b"], r.Lines.Select(l => l.ProviderPriceId));
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    public void a_blank_header_is_not_a_request_and_never_reprices(string header)
    {
        var r = SmokeTestPricing.Evaluate(Lines, header, RealKey, SmokePrice);

        Assert.Equal(SmokeTestPricing.Outcome.NotRequested, r.Outcome);
        Assert.Equal("price_real_a", r.Lines[0].ProviderPriceId);
    }

    [Fact]
    public void a_wrong_key_is_rejected_rather_than_repriced()
    {
        var r = SmokeTestPricing.Evaluate(Lines, "not-the-key", RealKey, SmokePrice);

        Assert.Equal(SmokeTestPricing.Outcome.Unauthorized, r.Outcome);
        Assert.DoesNotContain(r.Lines, l => string.Equals(l.ProviderPriceId, SmokePrice, StringComparison.Ordinal));
    }

    /// <summary>
    /// The reason a wrong key is an ERROR and not a silent fall-through. If a mistyped key sold at
    /// the listed price, the founder testing the overlay would be charged £49 — the exact bill the
    /// override exists to prevent. The caller maps Unauthorized to 401, so no session is created.
    /// </summary>
    [Fact]
    public void a_mistyped_key_must_not_quietly_sell_at_full_price()
    {
        var typo = RealKey[..^1] + "X";

        var r = SmokeTestPricing.Evaluate(Lines, typo, RealKey, SmokePrice);

        Assert.NotEqual(SmokeTestPricing.Outcome.NotRequested, r.Outcome);
        Assert.NotEqual(SmokeTestPricing.Outcome.Applied, r.Outcome);
        Assert.Equal(SmokeTestPricing.Outcome.Unauthorized, r.Outcome);
    }

    /// <summary>
    /// Fail closed on an unconfigured deployment. Were the empty expected key treated as a match,
    /// anyone who guessed the header name would buy every pack for the token price.
    /// </summary>
    [Theory]
    [InlineData(null)]
    [InlineData("")]
    public void no_configured_internal_key_means_nobody_can_reprice(string? expected)
    {
        var r = SmokeTestPricing.Evaluate(Lines, "", expected, SmokePrice);
        Assert.Equal(SmokeTestPricing.Outcome.NotRequested, r.Outcome);

        var attacker = SmokeTestPricing.Evaluate(Lines, "anything", expected, SmokePrice);
        Assert.Equal(SmokeTestPricing.Outcome.Unauthorized, attacker.Outcome);
        Assert.DoesNotContain(attacker.Lines, l => string.Equals(l.ProviderPriceId, SmokePrice, StringComparison.Ordinal));
    }

    [Fact]
    public void a_valid_key_with_no_smoke_price_configured_refuses_instead_of_charging_full_price()
    {
        var r = SmokeTestPricing.Evaluate(Lines, RealKey, RealKey, null);

        Assert.Equal(SmokeTestPricing.Outcome.NotConfigured, r.Outcome);
        Assert.Equal("price_real_a", r.Lines[0].ProviderPriceId);
    }

    [Fact]
    public void a_valid_key_reprices_every_line_in_the_basket()
    {
        var r = SmokeTestPricing.Evaluate(Lines, RealKey, RealKey, SmokePrice);

        Assert.Equal(SmokeTestPricing.Outcome.Applied, r.Outcome);
        Assert.All(r.Lines, l => Assert.Equal(SmokePrice, l.ProviderPriceId));
    }

    /// <summary>
    /// Fulfilment must still work. The webhook resolves which packs to grant from the session
    /// metadata, which is built from PackId — repricing that too would produce a paid order that
    /// grants nothing, and the smoke test would prove the payment while hiding a broken delivery.
    /// </summary>
    [Fact]
    public void repricing_preserves_pack_ids_so_entitlements_are_still_granted()
    {
        var r = SmokeTestPricing.Evaluate(Lines, RealKey, RealKey, SmokePrice);

        Assert.Equal(["pack-a", "pack-b"], r.Lines.Select(l => l.PackId));
    }

    [Fact]
    public void the_original_lines_are_not_mutated()
    {
        SmokeTestPricing.Evaluate(Lines, RealKey, RealKey, SmokePrice);

        Assert.Equal("price_real_a", Lines[0].ProviderPriceId);
        Assert.Equal("price_real_b", Lines[1].ProviderPriceId);
    }

    /// <summary>A near-miss key must fail exactly as hard as a wildly wrong one.</summary>
    [Theory]
    [InlineData("internal-key-abcdefghijklmno")]   // truncated
    [InlineData("internal-key-abcdefghijklmnopq")] // extra char
    [InlineData("Internal-key-abcdefghijklmnop")]  // case flip
    [InlineData(" internal-key-abcdefghijklmnop")] // leading space
    public void near_miss_keys_are_all_unauthorized(string provided)
    {
        var r = SmokeTestPricing.Evaluate(Lines, provided, RealKey, SmokePrice);

        Assert.Equal(SmokeTestPricing.Outcome.Unauthorized, r.Outcome);
    }
}
