using System.Net;
using System.Net.Http.Json;
using Microsoft.AspNetCore.Http;
using Store.Api.Common;
using Store.Api.Payments;
using Store.Tests.Endpoints;

namespace Store.Tests.Payments;

/// <summary>
/// The endpoint half: the buyer's id must actually reach the provider.
/// </summary>
/// <remarks>
/// Without these the whole chain could be wired, every unit test above could pass, and the
/// endpoint could still be handing the provider null -- which is exactly the shape of a feature
/// that looks finished and records nothing.
/// </remarks>
public sealed class CorrelationIdReachesTheProviderTests : IClassFixture<StoreApiFactory>
{
    private readonly StoreApiFactory _factory;

    public CorrelationIdReachesTheProviderTests(StoreApiFactory factory) => _factory = factory;

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

    [Fact]
    public async Task The_header_the_browser_sent_is_handed_to_the_provider()
    {
        var id = await ListedPackAsync("pack-corr-hosted");
        _factory.Payments.HostedHandle = new CheckoutHandle("https://checkout.stripe.com/c/pay/xyz", null);
        _factory.Payments.CorrelationIds.Clear();

        var client = Client();
        client.DefaultRequestHeaders.Add(HttpContextExtensions.CorrelationIdHeader, "browser-xyz-1");
        var response = await client.PostAsJsonAsync($"/packs/{id}/checkout", new { });

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("browser-xyz-1", Assert.Single(_factory.Payments.CorrelationIds));
    }

    [Fact]
    public async Task The_embedded_surface_carries_the_same_id_as_the_hosted_one()
    {
        // Two surfaces, one chain. If only one of them stamped the id, a purchase would be
        // traceable or not depending on which checkout the storefront happened to render.
        var id = await ListedPackAsync("pack-corr-embedded");
        _factory.Payments.EmbeddedHandle = new CheckoutHandle(string.Empty, "cs_test_secret");
        _factory.Payments.CorrelationIds.Clear();

        var client = Client();
        client.DefaultRequestHeaders.Add(HttpContextExtensions.CorrelationIdHeader, "browser-xyz-2");
        var response = await client.PostAsJsonAsync($"/packs/{id}/checkout", new { embedded = true });

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("browser-xyz-2", Assert.Single(_factory.Payments.CorrelationIds));
    }

    [Fact]
    public async Task A_buyer_that_sends_no_header_still_gets_an_id()
    {
        // A storefront that has not been updated, or any other client, must still be traceable.
        // Null here would mean the chain silently starts at the webhook.
        var id = await ListedPackAsync("pack-corr-none");
        _factory.Payments.HostedHandle = new CheckoutHandle("https://checkout.stripe.com/c/pay/xyz", null);
        _factory.Payments.CorrelationIds.Clear();

        var response = await Client().PostAsJsonAsync($"/packs/{id}/checkout", new { });

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var recorded = Assert.Single(_factory.Payments.CorrelationIds);
        Assert.False(string.IsNullOrEmpty(recorded));
    }

    [Fact]
    public async Task A_hostile_header_does_not_stop_the_buyer_paying()
    {
        // The whole point of the cap. A 10,000-character header must produce a normal checkout,
        // not a 500 and not a refused session.
        var id = await ListedPackAsync("pack-corr-hostile");
        _factory.Payments.HostedHandle = new CheckoutHandle("https://checkout.stripe.com/c/pay/xyz", null);
        _factory.Payments.CorrelationIds.Clear();

        var client = Client();
        client.DefaultRequestHeaders.Add(HttpContextExtensions.CorrelationIdHeader, new string('a', 10_000));
        var response = await client.PostAsJsonAsync($"/packs/{id}/checkout", new { });

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var recorded = Assert.Single(_factory.Payments.CorrelationIds);
        Assert.Equal(64, recorded!.Length);
    }
}
