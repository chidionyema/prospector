using System.Net;
using System.Net.Http.Json;
using Microsoft.AspNetCore.Http;
using Store.Api.Common;
using Store.Api.Payments;
using Store.Tests.Endpoints;

namespace Store.Tests.Payments;

public sealed class CorrelationIdMetadataTests
{
    private static readonly IReadOnlyList<CheckoutLine> OneLine =
        [new CheckoutLine("pack-1", "price_1")];

    [Fact]
    public void The_id_is_stamped_on_the_session_so_the_webhook_can_read_it_back()
    {
        var metadata = StripeProvider.BuildCheckoutMetadata(OneLine, "buyer-abc-123");

        Assert.Equal("buyer-abc-123", metadata[StripeProvider.CorrelationMetadataKey]);
    }

    [Fact]
    public void No_id_writes_no_key_at_all()
    {
        // So `corr` present always means `corr` usable, and no reader has to handle a blank one.
        var metadata = StripeProvider.BuildCheckoutMetadata(OneLine, null);

        Assert.DoesNotContain(StripeProvider.CorrelationMetadataKey, metadata.Keys);
    }

    [Fact]
    public void An_unusable_id_writes_no_key_either()
    {
        var metadata = StripeProvider.BuildCheckoutMetadata(OneLine, "!!!!");

        Assert.DoesNotContain(StripeProvider.CorrelationMetadataKey, metadata.Keys);
    }

    [Fact]
    public void A_hostile_id_cannot_make_stripe_refuse_the_session()
    {
        // The failure this prevents: a 10,000-character header turns every metadata value over
        // Stripe's 500-char limit, the session is never created, and the buyer sees a dead
        // button. The cap makes that impossible rather than unlikely.
        var metadata = StripeProvider.BuildCheckoutMetadata(OneLine, new string('a', 10_000));

        Assert.All(metadata.Values, v => Assert.True(v.Length <= 500, $"metadata value is {v.Length} chars"));
    }

    [Fact]
    public void The_pack_and_price_keys_are_untouched()
    {
        // The tracing key rides alongside the keys fulfilment depends on. If it ever displaced
        // one of them, every payment would be paid-but-unfulfilled.
        var metadata = StripeProvider.BuildCheckoutMetadata(OneLine, "buyer-abc-123");

        Assert.Equal("pack-1", metadata["pack_ids"]);
        Assert.Equal("price_1", metadata["price_ids"]);
        Assert.Equal("pack-1", metadata["pack_id"]);
    }
}
