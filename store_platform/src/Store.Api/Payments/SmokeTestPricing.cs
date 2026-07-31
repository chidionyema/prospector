namespace Store.Api.Payments;

using System.Security.Cryptography;
using System.Text;

/// <summary>
/// Substitutes a token-priced Stripe Price into a checkout, so the LIVE payment rail can be
/// exercised end to end without paying the listed price.
/// </summary>
/// <remarks>
/// <para>
/// Why this exists: the embedded checkout overlay cannot be proven by API calls alone. Stripe.js
/// accepts a malformed publishable key and only fails once Elements paints, and no automatic
/// fallback covers a bad RENDER (<c>checkoutRoute.ts</c> falls back only when the session REQUEST
/// fails). The only proof is a human completing a real live purchase — and at £49 a pack, that is
/// a bill for looking at a form.
/// </para>
/// <para>
/// The design constraint is that nothing here may become a discount a buyer can reach:
/// </para>
/// <list type="bullet">
/// <item>It is REQUEST-SCOPED, never a config flag. There is no enabled state to leave on by
/// accident; an override applies to exactly the one request that carried the header.</item>
/// <item>It is gated on <c>Store:InternalApiKey</c> — a server-side secret that the storefront
/// bundle never sees, compared in constant time. The public buy button cannot produce it.</item>
/// <item>The PackId is preserved and only the price id is swapped, so the webhook still grants
/// the real entitlement. That makes the smoke test cover fulfilment too, rather than testing a
/// payment for nothing.</item>
/// </list>
/// <para>
/// The one non-obvious rule: a PRESENT BUT INVALID header is an ERROR, never a silent fall
/// through to the listed price. Falling through would charge £49 for a mistyped test key — the
/// exact outcome the feature exists to prevent. Absent header = ordinary sale; bad header = no
/// sale at all.
/// </para>
/// </remarks>
public static class SmokeTestPricing
{
    /// <summary>Header carrying the internal key that authorises a token-priced checkout.</summary>
    public const string HeaderName = "X-Smoke-Test-Key";

    /// <summary>Config holding the Stripe Price id to charge instead of the listed price.</summary>
    public const string PriceIdSetting = "Stripe:SmokeTestPriceId";

    public enum Outcome
    {
        /// <summary>No header — an ordinary sale at the listed price.</summary>
        NotRequested,
        /// <summary>Header valid and a smoke price configured; lines were repriced.</summary>
        Applied,
        /// <summary>Header present but the key did not match. Reject; do NOT sell at full price.</summary>
        Unauthorized,
        /// <summary>Header valid but no smoke price configured. Reject for the same reason.</summary>
        NotConfigured,
    }

    public readonly record struct Result(Outcome Outcome, IReadOnlyList<CheckoutLine> Lines);

    /// <summary>
    /// Decide whether this request may be repriced, and reprice it if so.
    /// </summary>
    /// <param name="lines">The real lines, priced from each pack's provisioned Stripe Price.</param>
    /// <param name="providedKey">Raw <see cref="HeaderName"/> value; null/empty means absent.</param>
    /// <param name="expectedKey">The configured internal API key.</param>
    /// <param name="smokePriceId">The configured token Stripe Price id.</param>
    public static Result Evaluate(
        IReadOnlyList<CheckoutLine> lines,
        string? providedKey,
        string? expectedKey,
        string? smokePriceId)
    {
        // Absent header is the overwhelmingly common case: every real buyer. Return the lines
        // untouched before looking at any configuration.
        if (string.IsNullOrWhiteSpace(providedKey))
        {
            return new Result(Outcome.NotRequested, lines);
        }

        // Fail closed when no key is configured. Without this an unconfigured deployment would
        // treat "expected == empty" as a match and hand out token pricing to anyone who guessed
        // the header name.
        if (string.IsNullOrWhiteSpace(expectedKey)
            || !FixedTimeEqualsUtf8(providedKey, expectedKey))
        {
            return new Result(Outcome.Unauthorized, lines);
        }

        if (string.IsNullOrWhiteSpace(smokePriceId))
        {
            return new Result(Outcome.NotConfigured, lines);
        }

        // Swap the PRICE only. Keeping PackId means the session metadata, the webhook's pack
        // resolution, entitlement grant and download all run exactly as they do for a real sale.
        var repriced = new CheckoutLine[lines.Count];
        for (var i = 0; i < lines.Count; i++)
        {
            repriced[i] = lines[i] with { ProviderPriceId = smokePriceId };
        }

        return new Result(Outcome.Applied, repriced);
    }

    /// <summary>
    /// Constant-time compare that does not leak the expected length via an early return.
    /// </summary>
    /// <remarks>
    /// <see cref="CryptographicOperations.FixedTimeEquals"/> returns false immediately when the
    /// spans differ in length, so comparing raw UTF-8 would leak the key length through timing.
    /// Hashing both sides first makes every comparison run over 32 bytes regardless of input.
    /// </remarks>
    private static bool FixedTimeEqualsUtf8(string a, string b)
        => CryptographicOperations.FixedTimeEquals(
            SHA256.HashData(Encoding.UTF8.GetBytes(a)),
            SHA256.HashData(Encoding.UTF8.GetBytes(b)));
}
