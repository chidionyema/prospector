using Store.Catalog.Domain;

namespace Store.Tests.Domain;

public class MoneyTests
{
    [Theory]
    [InlineData(30, 3000)]
    [InlineData(29.99, 2999)]
    [InlineData(30.005, 3000)] // Banker's rounding: 3000.5 -> 3000 (even)
    [InlineData(30.015, 3002)] // Banker's rounding: 3001.5 -> 3002 (even)
    public void FromDecimal_ShouldApplyBankersRounding(decimal input, long expectedPence)
    {
        var result = Money.FromDecimal(input);
        Assert.Equal(expectedPence, result);
    }

    [Fact]
    public void ToDecimal_ShouldConvertCorrectly()
    {
        Assert.Equal(30.00m, Money.ToDecimal(3000));
        Assert.Equal(29.99m, Money.ToDecimal(2999));
    }

    [Fact]
    public void ToDisplayString_ShouldFormatCorrectly()
    {
        Assert.Equal("£30.00", Money.ToDisplayString(3000));
        Assert.Equal("£29.99", Money.ToDisplayString(2999));
        Assert.Equal("$30.00", Money.ToDisplayString(3000, "$"));
    }
}
