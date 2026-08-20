using System.Net;
using Microsoft.AspNetCore.Hosting;
using Microsoft.Extensions.DependencyInjection;
using Store.Api.Common;

namespace Store.Tests.Endpoints;

/// <summary>
/// One request must carry one correlation id, whichever component you ask.
/// </summary>
/// <remarks>
/// Two mechanisms mint an id here and neither knows about the other. <c>Crux.Observability</c>'s
/// middleware runs first, reads <c>X-Correlation-Id</c>, and mints a GUID when the caller sent
/// none; its id goes into the framework log scope and onto every outbound HTTP call. This
/// service's <c>GetCorrelationId()</c> is what the central log shipper and the Stripe metadata
/// use. When those two disagree, everything still looks fine: log lines have ids, Stripe has an
/// id, and none of them join up.
/// <para>
/// So this test asks the running API, not a constructed context. It also pins the package's item
/// key, which is a literal we read out of the shipped assembly rather than a constant the
/// compiler can check: if the package renames it, <c>PackageValue</c> comes back null and the
/// first assertion fails, instead of the ids silently drifting apart again.
/// </para>
/// </remarks>
public sealed class CorrelationIdIsOneIdTests : IClassFixture<StoreApiFactory>
{
    private readonly StoreApiFactory _factory;

    public CorrelationIdIsOneIdTests(StoreApiFactory factory) => _factory = factory;

    private (HttpClient Client, CorrelationIdRecorder Recorder) Instrumented()
    {
        var recorder = new CorrelationIdRecorder();
        var factory = _factory.WithWebHostBuilder(builder => builder.ConfigureServices(services =>
        {
            services.AddSingleton(recorder);
            services.AddSingleton<IStartupFilter>(_ => new CorrelationIdRecordingFilter(recorder));
        }));
        return (factory.CreateClient(), recorder);
    }

    [Fact]
    public async Task With_no_header_this_service_adopts_the_id_the_package_minted()
    {
        var (client, recorder) = Instrumented();

        var response = await client.GetAsync(new Uri("/catalog", UriKind.Relative));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        // Non-vacuity, and the pin on the package's key: an empty value here means we are reading
        // a key nothing writes, and every assertion below would pass without proving anything.
        Assert.False(string.IsNullOrEmpty(recorder.PackageValue));
        Assert.Equal(recorder.PackageValue, recorder.OurValue);
        // And it is the package's id we adopted, not our own fallback agreeing by luck.
        Assert.NotEqual(recorder.TraceIdentifier, recorder.OurValue);
    }

    [Fact]
    public async Task The_buyers_own_id_is_the_one_id_everywhere()
    {
        var (client, recorder) = Instrumented();
        client.DefaultRequestHeaders.Add(HttpContextExtensions.CorrelationIdHeader, "browser-sent-1");

        var response = await client.GetAsync(new Uri("/catalog", UriKind.Relative));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("browser-sent-1", recorder.OurValue);
        Assert.Equal("browser-sent-1", recorder.PackageValue);
    }
}
