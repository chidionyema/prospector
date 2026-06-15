namespace Store.Catalog.Domain;

/// <summary>
/// Handles money calculations using long (pence) and banker's rounding.
/// </summary>
public static class Money
{
    public const long DefaultPackPricePence = 3000; // £30.00

    public static long FromDecimal(decimal amount)
    {
        return (long)Math.Round(amount * 100, MidpointRounding.ToEven);
    }

    public static decimal ToDecimal(long pence)
    {
        return pence / 100m;
    }

    public static string ToDisplayString(long pence, string currencySymbol = "£")
    {
        return $"{currencySymbol}{ToDecimal(pence):N2}";
    }
}
