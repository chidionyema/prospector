using System.Net;
using System.Net.Http.Json;
using Microsoft.AspNetCore.Http;
using Store.Api.Common;
using Store.Api.Payments;
using Store.Tests.Endpoints;

namespace Store.Tests.Payments;

/// <summary>
/// One purchase must be greppable end to end: browser, API, provider, webhook, fulfilment.
/// </summary>
/// <remarks>
/// The chain has one hop nothing else in this codebase covers. The webhook that fulfils a
/// purchase arrives minutes later, from Stripe, on a connection carrying none of the buyer's
/// headers, so the id can only survive by riding on the checkout session's own metadata. That
/// makes an ordinary tracing feature touch the money path, and the tests below are as much
/// about what it must NOT do to a sale as about what it records.
/// <para>
/// The header comes from the buyer's browser, so it is hostile input that ends up in log lines,
/// in Stripe metadata and in the fulfilment trail. Stripe refuses to create a session whose
/// metadata value exceeds 500 characters -- so an uncapped header is not a logging bug, it is a
/// refusal to sell.
/// </para>
/// </remarks>
public sealed class CorrelationIdSanitiserTests
{
    [Theory]
    [InlineData("abc-123_ok.9", "abc-123_ok.9")]          // the ordinary case passes through
    [InlineData("has space", "hasspace")]
    [InlineData("drop\r\nforged: line", "dropforgedline")] // a forged second log line
    [InlineData("semi;colon|pipe", "semicolonpipe")]
    [InlineData("<script>alert(1)</script>", "scriptalert1script")]
    public void It_keeps_only_safe_characters(string raw, string expected)
        => Assert.Equal(expected, HttpContextExtensions.Sanitize(raw));

    [Theory]
    [InlineData("")]
    [InlineData(null)]
    [InlineData("!!!")]        // nothing survives the filter
    [InlineData("\r\n\r\n")]
    public void Nothing_usable_is_null_not_an_empty_string(string? raw)
    {
        // Null and "" are not interchangeable here: an empty string would be written into Stripe
        // metadata as a present-but-blank `corr`, and every later reader would have to decide
        // what a blank one means. Absent is the honest answer.
        Assert.Null(HttpContextExtensions.Sanitize(raw));
    }

    [Fact]
    public void A_hostile_length_is_capped_far_below_the_limit_that_would_stop_a_sale()
    {
        var attack = new string('a', 10_000);

        var clean = HttpContextExtensions.Sanitize(attack);

        Assert.NotNull(clean);
        Assert.Equal(64, clean!.Length);
        // 500 is Stripe's hard limit on a metadata value. Anything at or above it turns this
        // buyer's request into a failed session creation, which the buyer sees as a dead button.
        Assert.True(clean.Length < 500);
    }
}
