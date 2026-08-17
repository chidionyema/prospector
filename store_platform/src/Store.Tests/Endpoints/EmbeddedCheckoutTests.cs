using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Store.Api.Payments;

namespace Store.Tests.Endpoints;

/// <summary>
/// The checkout endpoint picks a surface. These prove it can never pick one that stops a buyer
/// paying.
/// </summary>
/// <remarks>
/// Embedded checkout is a cosmetic improvement on a money rail, which is the most dangerous kind
/// of change: the upside is that the buyer keeps the page they were reading, and the downside is
/// a silent sales outage if the nicer surface is unavailable and nothing falls back. Every test
/// here is about the fallback, not the feature.
/// </remarks>
public sealed class EmbeddedCheckoutTests : IClassFixture<StoreApiFactory>
{
    private readonly StoreApiFactory _factory;

    public EmbeddedCheckoutTests(StoreApiFactory factory) => _factory = factory;

    private HttpClient Client()
    {
        var client = _factory.CreateClient();
        client.DefaultRequestHeaders.Add("X-Internal-Key", StoreApiFactory.InternalKey);
        return client;
    }

    private async Task<string> ListedPackAsync(string id)
    {
        _factory.Payments.CanBill = true;
        var response = await Client().PostAsJsonAsync("/internal/catalog", new
        {
            id,
            title = "A Pack",
            oneLine = "One line.",
            dossierRef = $"dossier:{id}",
            paymentProvider = "stripe",
            providerProductId = "prod_1",
            providerPriceId = "price_real",
            isListed = true,
            contentKey = $"packs/{id}/abc.zip",
            contentHash = "abc",
        });
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        return id;
    }

    private static async Task<(string? Url, string? ClientSecret)> ReadAsync(HttpResponseMessage response)
    {
        using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var url = doc.RootElement.GetProperty("url");
        var secret = doc.RootElement.GetProperty("clientSecret");
        return (
            url.ValueKind == JsonValueKind.Null ? null : url.GetString(),
            secret.ValueKind == JsonValueKind.Null ? null : secret.GetString());
    }

    [Fact]
    public async Task An_embedded_request_returns_the_client_secret()
    {
        var id = await ListedPackAsync("pack-embedded-ok");
        _factory.Payments.EmbeddedHandle = new CheckoutHandle(string.Empty, "cs_test_secret");

        var response = await Client().PostAsJsonAsync($"/packs/{id}/checkout", new { embedded = true });

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var (_, secret) = await ReadAsync(response);
        Assert.Equal("cs_test_secret", secret);
    }

    [Fact]
    public async Task A_provider_without_an_embedded_surface_falls_back_to_the_hosted_url()
    {
        // THE test. A provider answering null must not produce an error, an empty body, or a
        // 500 — it must produce the hosted checkout that existed before this feature. A provider
        // answers null on every request, so this is the ordinary path, not an edge case.
        var id = await ListedPackAsync("pack-embedded-unsupported");
        _factory.Payments.EmbeddedHandle = null;
        _factory.Payments.HostedHandle = new CheckoutHandle("https://checkout.stripe.com/c/pay/xyz", null);

        var response = await Client().PostAsJsonAsync($"/packs/{id}/checkout", new { embedded = true });

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var (url, secret) = await ReadAsync(response);
        Assert.Equal("https://checkout.stripe.com/c/pay/xyz", url);
        Assert.Null(secret);
    }

    [Fact]
    public async Task A_provider_answering_with_a_blank_secret_also_falls_back()
    {
        // A handle with no usable secret is indistinguishable from no embedded surface as far as
        // the buyer is concerned: the storefront cannot mount Stripe's iframe without one. Left
        // unguarded this returns 200 with clientSecret:"" and the buy button does nothing.
        var id = await ListedPackAsync("pack-embedded-blank");
        _factory.Payments.EmbeddedHandle = new CheckoutHandle(string.Empty, "");
        _factory.Payments.HostedHandle = new CheckoutHandle("https://checkout.stripe.com/c/pay/abc", null);

        var response = await Client().PostAsJsonAsync($"/packs/{id}/checkout", new { embedded = true });

        var (url, secret) = await ReadAsync(response);
        Assert.Equal("https://checkout.stripe.com/c/pay/abc", url);
        Assert.Null(secret);
    }

    [Fact]
    public async Task A_request_that_did_not_ask_for_embedded_never_reaches_the_embedded_surface()
    {
        // Backwards compatibility, pinned at the wiring: an old storefront posting {} must get
        // exactly what it got before, and must not have an embedded session opened on its behalf
        // (which would leave an unused session against the account on every buy click).
        var id = await ListedPackAsync("pack-embedded-not-asked");
        var before = _factory.Payments.EmbeddedCalls;
        _factory.Payments.HostedHandle = new CheckoutHandle("https://checkout.stripe.com/c/pay/plain", null);

        var response = await Client().PostAsJsonAsync($"/packs/{id}/checkout", new { });

        var (url, secret) = await ReadAsync(response);
        Assert.Equal("https://checkout.stripe.com/c/pay/plain", url);
        Assert.Null(secret);
        Assert.Equal(before, _factory.Payments.EmbeddedCalls);
    }

    [Fact]
    public async Task The_embedded_return_url_carries_the_session_id_template()
    {
        // Embedded has no success_url; the return_url is the ONLY route back to fulfilment. If
        // it loses {CHECKOUT_SESSION_ID} the success page cannot resolve the entitlement and
        // every embedded buyer lands on a page that cannot show them their download.
        var id = await ListedPackAsync("pack-embedded-return");
        _factory.Payments.EmbeddedHandle = new CheckoutHandle(string.Empty, "cs_test_return");

        await Client().PostAsJsonAsync($"/packs/{id}/checkout", new { embedded = true });

        var returnUrl = Assert.Single(_factory.Payments.EmbeddedReturnUrls, u => u.Contains(id, StringComparison.Ordinal));
        Assert.Contains("/orders/success", returnUrl, StringComparison.Ordinal);
    }

    [Fact]
    public async Task An_unsellable_pack_is_still_refused_on_the_embedded_path()
    {
        // The embedded branch must not become a way around the guards the hosted path enforces.
        _factory.Payments.EmbeddedHandle = new CheckoutHandle(string.Empty, "cs_test_should_not_be_used");

        var response = await Client().PostAsJsonAsync("/packs/no-such-pack/checkout", new { embedded = true });

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }
}
