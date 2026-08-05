using Store.Catalog.Domain;

namespace Store.Tests.Domain;

/// <summary>
/// Pack.EffectiveFloorPence — the fulfilment floor, which is what makes a price change survivable.
/// </summary>
/// <remarks>
/// The failure these guard: fulfilment gates delivery on the catalogue, while Stripe Checkout
/// Sessions live up to 24h. So at the moment any price moves there are live sessions minted at
/// the old price, and a single price column strands a paying buyer in BOTH directions — a cut
/// strands buyers paying the new lower price against the old higher number, a rise strands
/// buyers paying the old lower price against the new higher one. The two need opposite write
/// orderings, so no ordering of two writes to one column fixes both.
///
/// The floor removes the race rather than narrowing it: it is the lowest amount any session that
/// could still be paid was minted at. These tests pin that property, including across repeated
/// changes inside one drain window, which is the case a hand-written ordering rule gets wrong.
/// </remarks>
public class PackPriceFloorTests
{
    private static readonly DateTime Now = new(2026, 8, 5, 12, 0, 0, DateTimeKind.Utc);
    private static readonly TimeSpan Drain = TimeSpan.FromHours(26);

    private static Pack PackAt(long pricePence) => new()
    {
        Id = "p1",
        Title = "T",
        OneLine = "O",
        DossierRef = "d1",
        PricePence = pricePence,
        MinBillablePence = pricePence,
        MinBillableEffectiveAt = Now.AddDays(-1),   // steady state: no change draining
    };

    /// <summary>
    /// Applies the same rule the PATCH /internal/catalog/{id}/price endpoint applies, so these
    /// tests pin the ORDERING SEMANTICS rather than a duplicate of the arithmetic.
    /// </summary>
    private static void Reprice(Pack pack, long newPricePence, DateTime at)
    {
        var currentFloor = pack.EffectiveFloorPence(at);
        pack.MinBillablePence = Math.Min(currentFloor, newPricePence);
        pack.MinBillableEffectiveAt = newPricePence > currentFloor ? at + Drain : at;
        pack.PricePence = newPricePence;
    }

    [Fact]
    public void Steady_state_floor_is_the_price()
    {
        Assert.Equal(4900, PackAt(4900).EffectiveFloorPence(Now));
    }

    [Fact]
    public void Cut_drops_the_floor_immediately_so_the_new_lower_price_fulfils()
    {
        var pack = PackAt(4900);
        Reprice(pack, 2900, Now);

        // The whole point of the cut case: a buyer paying the NEW price must be served at once.
        // Under the old single-column code this paid 2900 against a stale 4900 and was refused.
        Assert.Equal(2900, pack.EffectiveFloorPence(Now));
    }

    [Fact]
    public void Cut_still_fulfils_sessions_minted_at_the_old_higher_price()
    {
        var pack = PackAt(4900);
        Reprice(pack, 2900, Now);

        Assert.True(4900 >= pack.EffectiveFloorPence(Now));
    }

    [Fact]
    public void Rise_holds_the_old_floor_for_the_whole_drain_window()
    {
        var pack = PackAt(4900);
        Reprice(pack, 7900, Now);

        // A buyer holding a session minted at £49 has up to 24h to pay it. Refusing them would
        // mean taking 4900 and delivering nothing.
        Assert.Equal(4900, pack.EffectiveFloorPence(Now));
        Assert.Equal(4900, pack.EffectiveFloorPence(Now.AddHours(23)));
        Assert.Equal(4900, pack.EffectiveFloorPence(Now.AddHours(25)));
    }

    [Fact]
    public void Rise_closes_the_floor_to_the_new_price_once_the_window_has_passed()
    {
        var pack = PackAt(4900);
        Reprice(pack, 7900, Now);

        // And it closes on its own, with no scheduled job to miss: the drain is a stored
        // timestamp, so a process that was down for the entire window still computes this.
        Assert.Equal(7900, pack.EffectiveFloorPence(Now.AddHours(27)));
        Assert.Equal(7900, pack.EffectiveFloorPence(Now.AddDays(30)));
    }

    [Fact]
    public void Second_rise_inside_a_drain_window_extends_it_instead_of_lifting_the_floor()
    {
        var pack = PackAt(4900);
        Reprice(pack, 7900, Now);                    // £49 sessions in flight
        Reprice(pack, 9900, Now.AddHours(2));        // £79 sessions now in flight too

        // Taking min() against the CURRENT floor rather than against PricePence is what keeps
        // the £49 sessions served. Comparing against the price would have lifted the floor to
        // 7900 here and refused every one of them.
        Assert.Equal(4900, pack.EffectiveFloorPence(Now.AddHours(2)));
        Assert.Equal(4900, pack.EffectiveFloorPence(Now.AddHours(27)));
        Assert.Equal(9900, pack.EffectiveFloorPence(Now.AddHours(29)));
    }

    [Fact]
    public void Cut_inside_a_rise_drain_serves_every_price_in_flight()
    {
        var pack = PackAt(4900);
        Reprice(pack, 7900, Now);                    // £49 and £79 sessions both live
        Reprice(pack, 3900, Now.AddHours(2));        // then cut below both

        var floor = pack.EffectiveFloorPence(Now.AddHours(2));
        Assert.Equal(3900, floor);
        Assert.True(4900 >= floor);   // old £49 session still fulfils
        Assert.True(7900 >= floor);   // £79 session still fulfils
        Assert.True(3900 >= floor);   // and the new price fulfils
    }

    [Fact]
    public void Floor_never_exceeds_any_price_that_was_live_in_the_window()
    {
        // The invariant itself, over a run of changes: after each one, every price that could
        // still be sitting in an unpaid session must clear the floor.
        var pack = PackAt(4900);
        var live = new List<long> { 4900 };
        var at = Now;

        foreach (var next in new long[] { 7900, 3900, 14900, 1900, 9900 })
        {
            Reprice(pack, next, at);
            live.Add(next);
            var floor = pack.EffectiveFloorPence(at);
            Assert.All(live, price => Assert.True(
                price >= floor,
                $"a session minted at {price}p would be refused by floor {floor}p"));
            at = at.AddHours(1);   // every change lands inside the previous drain window
        }
    }

    [Fact]
    public void Underpayment_is_still_refused()
    {
        // The fence must keep doing its actual job. A cut is not an amnesty.
        var pack = PackAt(4900);
        Reprice(pack, 2900, Now);

        Assert.True(100 < pack.EffectiveFloorPence(Now));
        Assert.True(2899 < pack.EffectiveFloorPence(Now));
    }
}
