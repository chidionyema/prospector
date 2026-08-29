using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Store.Api.Common;

namespace Store.Tests.Endpoints;

/// <summary>Records both correlation ids from a real request, without changing the app.</summary>
/// <remarks>
/// A startup filter rather than a fake, because the claim under test is about the REAL pipeline:
/// that the id the observability package put on this request is the id this service hands to
/// Stripe. A test that constructed its own context would agree with itself and prove nothing.
/// </remarks>
internal sealed class CorrelationIdRecordingFilter : IStartupFilter
{
    private readonly CorrelationIdRecorder _recorder;

    public CorrelationIdRecordingFilter(CorrelationIdRecorder recorder) => _recorder = recorder;

    public Action<IApplicationBuilder> Configure(Action<IApplicationBuilder> next) => app =>
    {
        // Reads on the way OUT. By then every middleware downstream has run, including the
        // package's, so HttpContext.Items holds whatever the request really carried.
        app.Use(async (context, nextMiddleware) =>
        {
            await nextMiddleware().ConfigureAwait(false);
            _recorder.PackageValue =
                context.Items.TryGetValue(HttpContextExtensions.PackageCorrelationIdItemKey, out var v)
                    ? v as string
                    : null;
            _recorder.OurValue = context.GetCorrelationId();
            _recorder.TraceIdentifier = context.TraceIdentifier;
        });
        next(app);
    };
}
