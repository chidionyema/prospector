namespace Store.Api.Services;

/// <summary>
/// URL rules for the post-payment journey. Extracted from Program.cs and StripeProvider so the
/// two decisions that decide whether a paying buyer reaches their download are unit-testable.
///
/// The bug this exists to prevent: the storefront base and the API base were a single setting
/// (Store:PublicUrl). PROD_DEPLOY.md correctly set it to the API host — the magic-link email
/// needs the API's /orders/{token} route — but the same value was then used for the Stripe
/// success redirect, which points at /orders/success, a Next.js page the API does not serve.
/// Following the runbook exactly therefore sent every paying customer to a 404.
/// </summary>
public static class DeliveryUrls
{
    /// <summary>
    /// Where a buyer is sent after paying. Must resolve to the storefront.
    ///
    /// Order: an explicit storefront setting, then the CORS allowed-origin (which is by
    /// definition the storefront and is already set by the existing runbook, so deployments
    /// that predate the explicit setting still redirect correctly), then the request's own
    /// host — only ever right for a single-origin local run.
    /// </summary>
    public static string ResolveStorefrontBaseUrl(
        string? storefrontUrl,
        string? storefrontUrlEnv,
        string? allowedOrigin,
        string? allowedOriginEnv,
        string requestHostUrl)
    {
        var resolved = FirstNonBlank(storefrontUrl, storefrontUrlEnv, allowedOrigin, allowedOriginEnv)
            ?? requestHostUrl;
        return FirstOrigin(resolved);
    }

    /// <summary>
    /// The allowed-origin setting is a comma-separated list, because the apex, www and the
    /// .fly.dev host are three distinct browser origins that must all be permitted. A redirect
    /// can only target one of them, so when this falls back to that setting it takes the first
    /// entry — redirecting a paying buyer to the whole list would be a malformed URL, which is
    /// the same 404-class failure this file exists to prevent.
    /// </summary>
    private static string FirstOrigin(string value)
    {
        var parts = value.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        var first = parts.Length > 0 ? parts[0] : value;
        return first.TrimEnd('/');
    }

    /// <summary>
    /// Append Stripe's {CHECKOUT_SESSION_ID} template to a success URL. Stripe substitutes the
    /// real session id on redirect, which the storefront exchanges for the buyer's download
    /// link — so fulfilment does not depend on an email being delivered.
    /// </summary>
    public static string AppendSessionIdTemplate(string successUrl)
    {
        if (successUrl.Contains("{CHECKOUT_SESSION_ID}", StringComparison.Ordinal))
        {
            return successUrl;
        }

        var separator = successUrl.Contains('?', StringComparison.Ordinal) ? '&' : '?';
        return $"{successUrl}{separator}session_id={{CHECKOUT_SESSION_ID}}";
    }

    private static string? FirstNonBlank(params string?[] candidates)
        => Array.Find(candidates, c => !string.IsNullOrWhiteSpace(c));
}
