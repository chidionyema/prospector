using System.Net;
using System.Net.Http.Json;
using Microsoft.AspNetCore.Http;
using Store.Api.Common;
using Store.Api.Payments;
using Store.Tests.Endpoints;

namespace Store.Tests.Payments;

public sealed class CorrelationIdContextTests
{
    [Fact]
    public void A_clean_header_is_used()
    {
        var context = new DefaultHttpContext();
        context.Request.Headers[HttpContextExtensions.CorrelationIdHeader] = "buyer-abc-123";

        Assert.Equal("buyer-abc-123", context.GetCorrelationId());
    }

    [Fact]
    public void A_hostile_header_never_reaches_a_log_line_intact()
    {
        var context = new DefaultHttpContext { TraceIdentifier = "trace-1" };
        context.Request.Headers[HttpContextExtensions.CorrelationIdHeader] = "ok\r\nFORGED";

        Assert.Equal("okFORGED", context.GetCorrelationId());
    }

    [Fact]
    public void A_header_with_nothing_usable_falls_back_to_the_trace_id()
    {
        // Not to null and not to "". Every log line needs an id, and the framework's own is
        // always well formed, so the fallback can never itself be the hostile value.
        var context = new DefaultHttpContext { TraceIdentifier = "trace-2" };
        context.Request.Headers[HttpContextExtensions.CorrelationIdHeader] = "!!!!";

        Assert.Equal("trace-2", context.GetCorrelationId());
    }

    [Fact]
    public void No_header_falls_back_to_the_trace_id()
        => Assert.Equal("trace-3", new DefaultHttpContext { TraceIdentifier = "trace-3" }.GetCorrelationId());

    [Fact]
    public void An_id_adopted_by_the_webhook_wins_over_the_header()
    {
        // This is the webhook's case. Stripe's own request carries no buyer header, but if some
        // proxy ever adds one, the id read back off the session metadata is the one that ties
        // these log lines to the purchase, so it must win.
        var context = new DefaultHttpContext { TraceIdentifier = "trace-4" };
        context.Request.Headers[HttpContextExtensions.CorrelationIdHeader] = "from-a-proxy";

        context.SetCorrelationId("from-the-session");

        Assert.Equal("from-the-session", context.GetCorrelationId());
    }

    [Fact]
    public void Adopting_an_unusable_id_changes_nothing()
    {
        // A session created before this shipped carries no `corr`, so the webhook adopts null.
        // That must leave the request with its trace id rather than blanking it.
        var context = new DefaultHttpContext { TraceIdentifier = "trace-5" };

        context.SetCorrelationId(null);

        Assert.Equal("trace-5", context.GetCorrelationId());
    }

    [Fact]
    public void An_adopted_id_is_sanitised_too()
    {
        // A value read back off a provider is no more trustworthy than one read off a header.
        var context = new DefaultHttpContext { TraceIdentifier = "trace-6" };

        context.SetCorrelationId("sess\r\nFORGED");

        Assert.Equal("sessFORGED", context.GetCorrelationId());
    }
}
