using Store.Api.Services;
using Xunit;

namespace Store.Tests.Services;

/// <summary>
/// Regression tests for the post-payment URL rules.
///
/// These exist because a real launch blocker went undetected: the storefront base and the API
/// base were one setting, the runbook set it to the API host (correct for magic-link emails),
/// and the Stripe success redirect therefore pointed at /orders/success on a host that does not
/// serve it. Every paying buyer would have landed on a 404, and nothing in the build, the test
/// suite, or the runbook would have said so.
/// </summary>
public class DeliveryUrlsTests
{
    private const string Storefront = "https://prospector-store-web.fly.dev";
    private const string Api = "https://prospector-store-api.fly.dev";
    private const string RequestHost = "https://localhost:5291";

    [Fact]
    public void Redirect_Uses_Explicit_Storefront_Url_When_Set()
    {
        var result = DeliveryUrls.ResolveStorefrontBaseUrl(
            storefrontUrl: Storefront, storefrontUrlEnv: null,
            allowedOrigin: null, allowedOriginEnv: null, requestHostUrl: RequestHost);

        Assert.Equal(Storefront, result);
    }

    [Fact]
    public void Redirect_Falls_Back_To_Cors_Origin_Which_Is_The_Storefront()
    {
        // Deployments configured by the older runbook set only STORE_ALLOWED_ORIGIN. That value
        // is the storefront, so it is a safe fallback and keeps those deployments working.
        var result = DeliveryUrls.ResolveStorefrontBaseUrl(
            storefrontUrl: null, storefrontUrlEnv: null,
            allowedOrigin: null, allowedOriginEnv: Storefront, requestHostUrl: RequestHost);

        Assert.Equal(Storefront, result);
    }

    [Fact]
    public void Redirect_Takes_First_Origin_When_Cors_Setting_Is_A_List()
    {
        // STORE_ALLOWED_ORIGIN is comma-separated so the apex, www and the .fly.dev host can all
        // be permitted. Without this, the fallback would hand Stripe the entire comma-joined
        // string as success_url — a malformed redirect, the same class of failure as the 404.
        var result = DeliveryUrls.ResolveStorefrontBaseUrl(
            storefrontUrl: null, storefrontUrlEnv: null,
            allowedOrigin: null,
            allowedOriginEnv: $"https://mumchimp.com,https://www.mumchimp.com,{Storefront}",
            requestHostUrl: RequestHost);

        Assert.Equal("https://mumchimp.com", result);
    }

    [Fact]
    public void Redirect_Trims_Whitespace_And_Trailing_Slash_From_A_Listed_Origin()
    {
        // Hand-edited env files carry both. A trailing slash would produce
        // "https://mumchimp.com//orders/success".
        var result = DeliveryUrls.ResolveStorefrontBaseUrl(
            storefrontUrl: null, storefrontUrlEnv: null,
            allowedOrigin: " https://mumchimp.com/ , https://www.mumchimp.com ",
            allowedOriginEnv: null, requestHostUrl: RequestHost);

        Assert.Equal("https://mumchimp.com", result);
    }

    [Fact]
    public void Redirect_Never_Silently_Targets_The_Api_Host()
    {
        // The regression itself: with the storefront configured, the API's own host must not be
        // what a paying buyer is sent to.
        var result = DeliveryUrls.ResolveStorefrontBaseUrl(
            storefrontUrl: null, storefrontUrlEnv: Storefront,
            allowedOrigin: null, allowedOriginEnv: null, requestHostUrl: Api);

        Assert.NotEqual(Api, result);
        Assert.Equal(Storefront, result);
    }

    [Fact]
    public void Redirect_Uses_Request_Host_Only_When_Nothing_Is_Configured()
    {
        var result = DeliveryUrls.ResolveStorefrontBaseUrl(
            storefrontUrl: null, storefrontUrlEnv: null,
            allowedOrigin: null, allowedOriginEnv: null, requestHostUrl: RequestHost);

        Assert.Equal(RequestHost, result);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    public void Redirect_Treats_Blank_Configuration_As_Unset(string blank)
    {
        // An env var present but empty is a common deploy slip. It must not win over a real value.
        var result = DeliveryUrls.ResolveStorefrontBaseUrl(
            storefrontUrl: blank, storefrontUrlEnv: blank,
            allowedOrigin: Storefront, allowedOriginEnv: null, requestHostUrl: RequestHost);

        Assert.Equal(Storefront, result);
    }

    [Fact]
    public void Redirect_Strips_Trailing_Slash_So_Paths_Do_Not_Double_Up()
    {
        var result = DeliveryUrls.ResolveStorefrontBaseUrl(
            storefrontUrl: Storefront + "/", storefrontUrlEnv: null,
            allowedOrigin: null, allowedOriginEnv: null, requestHostUrl: RequestHost);

        Assert.Equal(Storefront, result);
        Assert.DoesNotContain("//orders", $"{result}/orders/success", StringComparison.Ordinal);
    }

    [Fact]
    public void Success_Url_Carries_The_Session_Template_So_Download_Works_Without_Email()
    {
        // The success page exchanges this id for the buyer's entitlement. Without it the page
        // can only tell them to check an inbox, which is the failure mode that let a buyer pay
        // and receive nothing when the mail sender was unconfigured.
        var result = DeliveryUrls.AppendSessionIdTemplate($"{Storefront}/orders/success?pack=abc");

        Assert.Equal($"{Storefront}/orders/success?pack=abc&session_id={{CHECKOUT_SESSION_ID}}", result);
    }

    [Fact]
    public void Success_Url_Uses_A_Question_Mark_When_There_Is_No_Query_Yet()
    {
        var result = DeliveryUrls.AppendSessionIdTemplate($"{Storefront}/orders/success");

        Assert.Equal($"{Storefront}/orders/success?session_id={{CHECKOUT_SESSION_ID}}", result);
    }

    [Fact]
    public void Success_Url_Is_Not_Double_Stamped()
    {
        var once = DeliveryUrls.AppendSessionIdTemplate($"{Storefront}/orders/success?pack=abc");
        var twice = DeliveryUrls.AppendSessionIdTemplate(once);

        Assert.Equal(once, twice);
    }
}
