namespace Store.Catalog.Domain;

public class Pack
{
    public required string Id { get; set; }
    public required string Title { get; set; }
    public required string OneLine { get; set; }
    public long PricePence { get; set; }

    // The fulfilment floor, which is NOT the same thing as the price and must not be confused
    // with it. PricePence is the amount a freshly created checkout session mints at, and the
    // amount the storefront shows. This is the lowest amount that any session which could still
    // be paid right now was minted at.
    //
    // They are the same number in the steady state and diverge only while a price change drains.
    // The reason they must be separate is that fulfilment gates delivery on the pack's CURRENT
    // price (FulfilmentService, the founder-fence check), while Stripe Checkout Sessions live up
    // to 24h — so a single column breaks in BOTH directions. On a cut from £49 to £29 with the
    // provider changed first, the buyer pays 2900 while the pack still says 4900, and is charged
    // without being delivered. On a rise from £49 to £79 with the catalogue changed first, a buyer
    // holding a session minted at £49 pays 4900 against a 7900 floor, and is likewise charged
    // without being delivered.
    //
    // Opposite orderings, so no ordering of two writes to one column is safe for both. Splitting
    // the columns removes the race entirely rather than narrowing it.
    //
    // Use EffectiveFloorPence(now) to read it — never this field directly. The drain is expressed
    // as data (this value plus MinBillableEffectiveAt) rather than as a scheduled job, so there is
    // no tick to miss, no cron to drift, and the floor is correct even if the process was down for
    // the whole drain window.
    public long MinBillablePence { get; set; }

    // When the drain ends and the floor rejoins PricePence. In the past (or default) means the
    // pack is in its steady state and PricePence is the floor.
    public DateTime MinBillableEffectiveAt { get; set; }

    /// <summary>
    /// The amount a payment must cover to be fulfilled, as of <paramref name="now"/>.
    ///
    /// Deliberately conservative: while a rise drains, this is the OLD, lower floor, so a buyer
    /// who is mid-checkout at the old price is still served. A cut needs no drain — the new price
    /// is already the minimum, so old higher-priced sessions clear it — and the mutator sets
    /// MinBillableEffectiveAt to now in that case, making this return the new price immediately.
    ///
    /// Never returns more than the floor a live session could have been minted at, which is the
    /// whole invariant: this fence exists to refuse genuine underpayment, and it must never be
    /// the reason a paying customer is refused.
    /// </summary>
    public long EffectiveFloorPence(DateTime now) =>
        now >= MinBillableEffectiveAt ? PricePence : MinBillablePence;

    // The same pack's price in US cents, for buyers billed in USD (founder decision 2026-08-14:
    // "as a US buyer you want to be charged in USD"). NULL means this pack has no USD price, and
    // that is the safe default every pack starts at: the fulfilment fence refuses a currency the
    // pack has no floor in, so a pack that was never given a USD price cannot be billed in one.
    //
    // A SEPARATE COLUMN, NOT A CONVERSION. The alternative — convert the paid USD amount to pence
    // at some rate and compare against PricePence — makes the fence's verdict depend on which rate
    // it happened to read, so a buyer who paid exactly the displayed price is refused whenever the
    // rate moved between checkout and webhook. The rung is declared (config.yaml listing.pricing,
    // usd_rungs, approved 2026-08-14), never computed at charge time.
    //
    // Cents, not pence: the name says the unit because the two are both "minor units of 100" and
    // that is exactly what makes a silent mix-up invisible. 2499 here is $24.99, not £24.99.
    public long? PriceUsdCents { get; set; }

    // The USD twin of MinBillablePence — the floor a live USD session could have been minted at
    // while a price change drains. Same race, same fix; see the long comment above MinBillablePence.
    // Null when PriceUsdCents is null, and treated as equal to PriceUsdCents when a USD price
    // exists but no drain is in progress.
    public long? MinBillableUsdCents { get; set; }

    /// <summary>
    /// The amount a payment in <paramref name="currency"/> must cover to be fulfilled, in that
    /// currency's minor units — or null when the pack carries no price in that currency at all.
    ///
    /// Null is the refusal: it is the one signal that keeps the pre-USD safety property intact.
    /// Before this existed the fence compared a bare amount against a GBP-only column and refused
    /// anything non-GBP outright; now it refuses anything the pack has no floor in, which is the
    /// same refusal generalised rather than weakened. Nothing becomes billable by adding a column.
    /// </summary>
    public long? EffectiveFloorMinorUnits(string currency, DateTime now)
    {
        if (string.Equals(currency, "GBP", StringComparison.OrdinalIgnoreCase))
        {
            return EffectiveFloorPence(now);
        }

        if (string.Equals(currency, "USD", StringComparison.OrdinalIgnoreCase) && PriceUsdCents is { } usd)
        {
            return now >= MinBillableEffectiveAt ? usd : (MinBillableUsdCents ?? usd);
        }

        return null;
    }

    public string PaymentProvider { get; set; } = "stripe";
    public string? ProviderProductId { get; set; }
    public string? ProviderPriceId { get; set; }
    public bool IsListed { get; set; }

    // Hidden from the browse catalogue while staying fully sellable at its real price.
    //
    // This exists so fulfilment can be proved end to end for the price of the pack, repeatably,
    // WITHOUT weakening a fence. IsListed does two jobs — "appears in GET /catalog" and "can be
    // bought at all" — and it is the second that makes withdrawing a pack actually stop sales
    // (Program.cs:206, CheckoutEndpoints.cs:271). A cheap probe pack therefore cannot be
    // "unlisted": unlisted means unbuyable. Splitting off the browse half is the only way to get
    // one that is out of the shop window and still a real, honestly-priced sale.
    //
    // Deliberately NOT a sellability flag. Nothing becomes buyable that was not buyable before:
    // a hidden pack is still IsListed, still needs a billable price, and is still refused by the
    // underpayment fence below its own PricePence. Quarantine keeps working exactly as it did —
    // IsListed=false stops the sale regardless of this flag.
    public bool HiddenFromCatalogue { get; set; }

    // Why the pack was last withdrawn from sale, set by PATCH /internal/catalog/{id}/listing.
    // Kept after a re-list rather than cleared, so the history of a pack that has been pulled
    // and restored is still legible; DelistedAt tells you whether it applies right now.
    public string? DelistReason { get; set; }
    public DateTime? DelistedAt { get; set; }

    public required string DossierRef { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    // Deliverable content (the purchased ZIP) in object storage. A pack must never be
    // listed (IsListed=true) unless ContentKey is set — selling something undeliverable
    // is the cardinal sin of this layer. ContentVersion bumps on each republish so
    // existing entitlements can pin the version they bought.
    public string? ContentKey { get; set; }
    public string? ContentHash { get; set; }
    public int ContentVersion { get; set; } = 1;

    // Storefront conversion metadata, set by the engine at publish time from the verified
    // dossier. All optional — a pack lists without them. Arrays and the financial snapshot
    // are stored as JSON text and re-hydrated by the read API (SQLite has no array column).
    /// <summary>
    /// The engine's own short (max 60 char) description of what the business DOES, written for
    /// the shelf card's heading. Distinct from <see cref="Headline"/>, which is the outcome
    /// promise and runs to 10-15 words. Length is enforced engine-side by DISCARDING an
    /// over-length line rather than truncating it, so a value present here is one the engine
    /// stood behind whole; null simply means the card falls back to the title.
    /// </summary>
    public string? CardLine { get; set; }
    public string? Headline { get; set; }
    public string? Subhead { get; set; }
    public string? ProofPoint { get; set; }
    public string? WhoPays { get; set; }
    public string? EffortTag { get; set; }
    public string? TimeToFirstRevenue { get; set; }
    public string? QaVerdictSummary { get; set; }
    public int? SourceCount { get; set; }
    public DateTime? VerifiedAt { get; set; }
    public string? WhatYouGetJson { get; set; }
    public string? SampleExtractJson { get; set; }
    public string? FinancialSnapshotJson { get; set; }

    // The jurisdiction the OPPORTUNITY is in ("uk", "us", "us-tx"), not the buyer's
    // locale — and still not a pricing input. Currency follows the BUYER (PriceUsdCents above),
    // not the pack: a US buyer may buy a UK-market pack and is billed in USD for it, and a UK
    // buyer may buy a US-market pack and is billed in GBP. This is a browse/filter facet and a
    // disclosure. Null on every pack published before the engine had a market dimension.
    public string? Market { get; set; }

    // The audience persona the engine GENERATED this pack for ("smb_owner", "primary_carer",
    // ...). A disclosure and an analytics dimension, never a gate: nothing about sellability,
    // price or delivery reads it, and a buyer outside the persona is a perfectly good buyer.
    //
    // Not a member of PackFacets on purpose. PackFacets.Advantage already contains a value
    // spelled "audience" that means the opposite end of the transaction — "this buyer already
    // HAS an audience to sell to" — so folding the persona into the facet vocabulary would put
    // two unrelated meanings behind one word in the browse filter.
    //
    // Null on every pack published before the engine carried the persona through publish
    // (the value was stamped on the dossier from the start and dropped at the boundary), and
    // on any pack whose generation did not stamp one. Null means unknown, never "general
    // audience" — an inferred persona would be a claim the engine never made.
    public string? Audience { get; set; }

    // Discovery facets — the closed vocabulary in PackFacets, emitted by the engine from a
    // verified dossier and validated at the publish boundary. All nullable on purpose: an
    // untagged pack lists under "All" and never under a specific value. Nothing here may be
    // inferred from pack text (that is what the deleted browser-side sector regex did, and
    // it labelled a metal fabricator a gardening business in public).
    public string? Sector { get; set; }
    public string? Payer { get; set; }
    public string? Effort { get; set; }
    public string? Commitment { get; set; }
    public string? Mechanism { get; set; }

    // Multi-valued (0-3 of PackFacets.Advantage) stored as JSON text — SQLite has no array
    // column, same convention as WhatYouGetJson above.
    public string? AdvantagesJson { get; set; }
}
