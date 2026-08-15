using Stripe;
using Stripe.Checkout;
using Store.Api.Services;

namespace Store.Api.Payments;

public sealed class StripeProvider(IConfiguration config, ILogger<StripeProvider> logger) : IPaymentProvider
{
    /// <summary>
    /// Suffix appended to the buyer's card statement line, which renders as "&lt;prefix&gt;* &lt;suffix&gt;".
    /// </summary>
    /// <remarks>
    /// Verified 2026-07-30 against the live account acct_1TjzYHPMafoirYBF:
    /// <c>settings.card_payments.statement_descriptor_prefix</c> is <c>PROSPECTOR</c>, so with no
    /// suffix the statement reads only PROSPECTOR for a purchase made on mumchimp.com — the classic
    /// "I don't recognise this charge" chargeback trigger. This makes it "PROSPECTOR* MUMCHIMP".
    /// <para>
    /// The prefix itself cannot be changed from code: <c>POST /v1/accounts/{id}</c> returns
    /// "You cannot use this method on your own account: you may only use it on connected accounts."
    /// It is Dashboard-only — https://dashboard.stripe.com/settings/public — set the public business
    /// name and the card statement descriptor to MUMCHIMP there. Once done this suffix is redundant
    /// but stays harmless. Stripe caps prefix+suffix at 22 chars and rejects &lt; &gt; \ " ' *.
    /// </para>
    /// </remarks>
    private const string StatementDescriptorSuffix = "MUMCHIMP";

    /// <summary>
    /// Hard cap on packs per checkout. Stripe caps a metadata VALUE at 500 characters, and the
    /// session carries two parallel CSVs — pack ids (16 chars each) and price ids (~30 each).
    /// Price ids are the binding side: ~16 would fit. Ten leaves real headroom, and a basket of
    /// ten £49 packs is already far outside any observed order.
    /// </summary>
    public const int MaxCheckoutLines = 10;

    public string Name => "stripe";

    public async Task<WebhookVerifyResult> VerifyAndParseAsync(HttpRequest request, string rawBody, IConfiguration config, ILogger logger)
    {
        var secret = config["Stripe:WebhookSecret"];
        if (string.IsNullOrEmpty(secret))
        {
            logger.LogError("Stripe webhook secret is not configured.");
            return new WebhookVerifyResult(false, null, "secret-not-configured");
        }

        if (!request.Headers.TryGetValue("Stripe-Signature", out var signatureHeader))
        {
            logger.LogWarning("Stripe webhook missing signature header.");
            return new WebhookVerifyResult(false, null, "missing-signature");
        }

        try
        {
            // throwOnApiVersionMismatch: false — live accounts stamp events with the
            // account's API version, which routinely differs from the SDK's pinned
            // version. Throwing on mismatch would reject valid production webhooks and
            // silently drop fulfilment. Signature + timestamp tolerance still enforced.
            var stripeEvent = await Task.Run(() => EventUtility.ConstructEvent(
                rawBody, signatureHeader, secret, throwOnApiVersionMismatch: false)).ConfigureAwait(false);

            // P1-1 — money reversals revoke access instead of granting it.
            if (TryParseReversal(stripeEvent, out var reversalResult))
            {
                return reversalResult;
            }

            if (!string.Equals(stripeEvent.Type, "checkout.session.completed", StringComparison.Ordinal))
            {
                return new WebhookVerifyResult(false, null, stripeEvent.Type, Ignored: true);
            }

            if (stripeEvent.Data.Object is not Session session)
            {
                return new WebhookVerifyResult(false, null, "invalid-session-object");
            }

            var txn = await BuildTransactionAsync(session, stripeEvent, CancellationToken.None).ConfigureAwait(false);
            return new WebhookVerifyResult(true, txn, null);
        }
        catch (LineItemsUnavailableException ex)
        {
            // A multi-pack basket whose per-line amounts could not be read. Granting on a guess
            // would defeat FulfilmentService's price fence, so refuse the event and let Stripe
            // retry it — the money is already captured and the event is replayable.
            logger.LogError(ex, "Could not read Stripe line items; deferring fulfilment for retry.");
            return new WebhookVerifyResult(false, null, "line-items-unavailable");
        }
        catch (StripeException ex)
        {
            logger.LogWarning(ex, "Stripe signature verification failed.");
            return new WebhookVerifyResult(false, null, "invalid-signature");
        }
        catch (Exception ex)
        {
            logger.LogError(ex, "Failed to process Stripe webhook.");
            return new WebhookVerifyResult(false, null, "malformed");
        }
    }

    // P1-1 — recognise refund/dispute events and translate them into a provider-agnostic
    // reversal. Returns false for any non-reversal event so the caller continues to its
    // normal grant path. The boolean+out keeps VerifyAndParseAsync within the length limit.
    private static bool TryParseReversal(Stripe.Event stripeEvent, out WebhookVerifyResult result)
    {
        if (string.Equals(stripeEvent.Type, "charge.refunded", StringComparison.Ordinal))
        {
            // Partial refunds still revoke: a £30 digital pack is all-or-nothing.
            result = stripeEvent.Data.Object is Charge charge
                ? new WebhookVerifyResult(true, null, stripeEvent.Type, Reversal: new PaymentReversal(
                    "stripe", stripeEvent.Id, charge.PaymentIntentId ?? charge.Id, "refund"))
                : new WebhookVerifyResult(false, null, "invalid-charge-object");
            return true;
        }

        if (string.Equals(stripeEvent.Type, "charge.dispute.created", StringComparison.Ordinal))
        {
            result = stripeEvent.Data.Object is Dispute dispute
                ? new WebhookVerifyResult(true, null, stripeEvent.Type, Reversal: new PaymentReversal(
                    "stripe", stripeEvent.Id, dispute.PaymentIntentId ?? dispute.ChargeId ?? "", "dispute"))
                : new WebhookVerifyResult(false, null, "invalid-dispute-object");
            return true;
        }

        result = null!;
        return false;
    }

    private static async Task<PaymentTransaction> BuildTransactionAsync(
        Session session, Stripe.Event stripeEvent, CancellationToken ct) =>
        new(
            Provider: "stripe",
            TransactionId: session.PaymentIntentId ?? session.Id,
            BuyerEmail: session.CustomerDetails?.Email ?? session.CustomerEmail ?? "",
            Currency: session.Currency?.ToUpperInvariant() ?? "GBP",
            Country: session.CustomerDetails?.Address?.Country ?? "",
            TotalAmountPence: session.AmountTotal ?? 0,
            OccurredAt: stripeEvent.Created,
            Items: await ExtractItemsAsync(session, ct).ConfigureAwait(false));

    /// <summary>
    /// Resolve which packs were bought and — critically — how much was actually paid for each.
    /// </summary>
    /// <remarks>
    /// The per-item amount is not cosmetic: FulfilmentService refuses to grant an entitlement
    /// unless the item's paid amount covers the catalogue price (the founder fence against
    /// coupons, mispriced provider products and forged underpayments). A single-pack session can
    /// use the session total for that comparison because the total IS that pack. A basket cannot
    /// — handing every item the whole basket total would make the fence pass for anything, so a
    /// £98 two-pack session would satisfy a fence meant to prove £49 was paid for each. For a
    /// basket we therefore read what Stripe actually charged per line.
    /// </remarks>
    private static async Task<List<PurchasedItem>> ExtractItemsAsync(Session session, CancellationToken ct)
    {
        var packIds = ReadCsvMetadata(session.Metadata, "pack_ids");

        if (packIds.Count == 0)
        {
            // Sessions created before multi-item checkout carry only the singular key. Those
            // may still be in flight when this deploys, so honour them unchanged.
            return session.Metadata is not null
                && session.Metadata.TryGetValue("pack_id", out var legacyId)
                && !string.IsNullOrEmpty(legacyId)
                    ? [new PurchasedItem(legacyId, session.AmountTotal ?? 0)]
                    : [];
        }

        if (packIds.Count == 1)
        {
            return [new PurchasedItem(packIds[0], session.AmountTotal ?? 0)];
        }

        var priceIds = ReadCsvMetadata(session.Metadata, "price_ids");
        // Checked before the round trip, not only inside PairBasketItems: a session whose two
        // CSVs disagree is unpairable whatever Stripe returns, so asking is pure waste.
        RequirePairableCsvs(session.Id, packIds, priceIds);

        var paidByPrice = await LoadPaidAmountsByPriceAsync(session.Id, ct).ConfigureAwait(false);
        return PairBasketItems(session.Id, packIds, priceIds, paidByPrice);
    }

    /// <summary>
    /// Pair each pack in a basket with what was actually paid for it, or refuse.
    /// </summary>
    /// <remarks>
    /// Every failure here throws rather than degrading, because the only degradations available
    /// are both wrong: pair on a guess, or hand an item an amount it did not earn. Either would
    /// walk a pack past FulfilmentService's price fence. Throwing fails the webhook, which Stripe
    /// then retries — the buyer's money is captured and nothing is granted meanwhile.
    /// Separated from the Stripe call so the pairing rules are testable without a network.
    /// </remarks>
    internal static List<PurchasedItem> PairBasketItems(
        string sessionId,
        IReadOnlyList<string> packIds,
        IReadOnlyList<string> priceIds,
        IReadOnlyDictionary<string, long> paidByPrice)
    {
        RequirePairableCsvs(sessionId, packIds, priceIds);

        var items = new List<PurchasedItem>(packIds.Count);
        for (var i = 0; i < packIds.Count; i++)
        {
            if (!paidByPrice.TryGetValue(priceIds[i], out var paid))
            {
                throw new LineItemsUnavailableException(
                    $"Session {sessionId} line for price {priceIds[i]} was not returned by Stripe.");
            }
            items.Add(new PurchasedItem(packIds[i], paid));
        }
        return items;
    }

    /// <summary>
    /// The pack-id and price-id CSVs are written together and are meaningless apart. Rather than
    /// guess a pairing, refuse: Stripe retries the webhook, and a human sees the error.
    /// </summary>
    private static void RequirePairableCsvs(
        string sessionId, IReadOnlyList<string> packIds, IReadOnlyList<string> priceIds)
    {
        if (priceIds.Count != packIds.Count)
        {
            throw new LineItemsUnavailableException(
                $"Session {sessionId} has {packIds.Count} pack ids but {priceIds.Count} price ids.");
        }
    }

    /// <summary>
    /// What Stripe charged per line, keyed by price id. Uses <c>AmountSubtotal</c> — the line
    /// total after discounts but before tax — because that is the number the price fence is
    /// asking about: did this buyer pay the listed price for this pack. Tax varies by the
    /// buyer's country and must not count towards it; a coupon must count against it.
    /// </summary>
    private static async Task<Dictionary<string, long>> LoadPaidAmountsByPriceAsync(string sessionId, CancellationToken ct)
    {
        try
        {
            var lineItems = await new SessionLineItemService()
                .ListAsync(sessionId, new SessionLineItemListOptions { Limit = 100 }, cancellationToken: ct)
                .ConfigureAwait(false);

            var byPrice = new Dictionary<string, long>(StringComparer.Ordinal);
            foreach (var line in lineItems.Data)
            {
                var priceId = line.Price?.Id;
                if (string.IsNullOrEmpty(priceId))
                {
                    continue;
                }
                // A basket holds distinct packs (the checkout endpoint rejects duplicates), so
                // one line per price. Summing rather than assigning keeps this correct anyway if
                // that ever stops being true.
                byPrice[priceId] = byPrice.GetValueOrDefault(priceId) + line.AmountSubtotal;
            }
            return byPrice;
        }
        catch (StripeException ex)
        {
            throw new LineItemsUnavailableException($"Stripe would not list line items for {sessionId}.", ex);
        }
    }

    /// <summary>Read a comma-separated metadata value into its non-empty parts.</summary>
    private static List<string> ReadCsvMetadata(Dictionary<string, string>? metadata, string key)
    {
        if (metadata is null || !metadata.TryGetValue(key, out var raw) || string.IsNullOrWhiteSpace(raw))
        {
            return [];
        }
        return [.. raw.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)];
    }

    public async Task<ProviderProduct> CreateProductAsync(string title, long pricePence, string currency, IDictionary<string, string> metadata, CancellationToken ct)
    {
        EnsureStripeConfigured();

        // P1-2 — idempotency keys: a network retry must not create a duplicate Stripe
        // Product/Price. Key off a stable seed (candidate_id when provided, else title).
        var seed = metadata.TryGetValue("candidate_id", out var cid) && !string.IsNullOrEmpty(cid)
            ? cid : title;

        var productOptions = new ProductCreateOptions
        {
            Name = title,
            Metadata = new Dictionary<string, string>(metadata, StringComparer.Ordinal)
        };
        var productService = new ProductService();
        var product = await productService.CreateAsync(
            productOptions,
            new RequestOptions { IdempotencyKey = $"product-create-{seed}" },
            ct).ConfigureAwait(false);

        var priceOptions = new PriceCreateOptions
        {
            Product = product.Id,
            UnitAmount = pricePence,
            Currency = currency.ToLowerInvariant(),
            Metadata = new Dictionary<string, string>(metadata, StringComparer.Ordinal)
        };
        var priceService = new PriceService();
        var price = await priceService.CreateAsync(
            priceOptions,
            new RequestOptions { IdempotencyKey = $"price-create-{seed}-{pricePence}-{currency.ToLowerInvariant()}" },
            ct).ConfigureAwait(false);

        return new ProviderProduct(product.Id, price.Id);
    }

    public async Task<CheckoutHandle> CreateCheckoutAsync(IReadOnlyList<CheckoutLine> lines, string? buyerEmail, string successUrl, string cancelUrl, CancellationToken ct)
    {
        var options = BuildSessionOptions(lines, buyerEmail);
        // Stripe substitutes the literal {CHECKOUT_SESSION_ID} template on redirect. The
        // storefront uses it to resolve the buyer's entitlement and render a real download
        // link on the success page, so fulfilment no longer depends on an email arriving.
        options.SuccessUrl = AppendSessionIdTemplate(successUrl);
        options.CancelUrl = cancelUrl;

        var service = new SessionService();
        var session = await service.CreateAsync(options, cancellationToken: ct).ConfigureAwait(false);

        return new CheckoutHandle(session.Url, session.ClientSecret);
    }

    /// <summary>
    /// The same session, rendered inside the pack page instead of on checkout.stripe.com.
    /// </summary>
    /// <remarks>
    /// Identical in every respect that touches money: same line items, same metadata (so the
    /// webhook grants the same entitlements), same statement descriptor, same automatic tax.
    /// Only the surface differs, and it is built from the SAME <see cref="BuildSessionOptions"/>
    /// so the two cannot drift into billing differently.
    /// <para>
    /// Returns null rather than throwing when Stripe answers without a client secret — the
    /// caller then serves the hosted URL. A buyer must never be blocked from paying because the
    /// embedded surface was unavailable.
    /// </para>
    /// <para>
    /// Note there is no cancel_url: an embedded checkout has nothing to cancel TO, the buyer is
    /// already on the pack page. Stripe rejects a session carrying both success_url and
    /// ui_mode=embedded, which is why this is a separate call and not a flag.
    /// </para>
    /// </remarks>
    public async Task<CheckoutHandle?> CreateEmbeddedCheckoutAsync(
        IReadOnlyList<CheckoutLine> lines, string? buyerEmail, string returnUrl, CancellationToken ct)
    {
        var options = BuildSessionOptions(lines, buyerEmail);
        options.UiMode = "embedded";
        options.ReturnUrl = AppendSessionIdTemplate(returnUrl);

        var service = new SessionService();
        var session = await service.CreateAsync(options, cancellationToken: ct).ConfigureAwait(false);

        return string.IsNullOrEmpty(session.ClientSecret)
            ? null
            : new CheckoutHandle(session.Url ?? string.Empty, session.ClientSecret);
    }

    /// <summary>
    /// The one currency this session bills in, as Stripe wants it (lower case).
    /// </summary>
    /// <remarks>
    /// One session, one currency. Stripe would accept a mixed list and bill the whole session in
    /// the session's currency, so taking <c>lines[0]</c> would charge a buyer the USD amount for
    /// one pack and the dollar figure of the PENCE amount for the next. Refusing is the only safe
    /// reading: the caller resolves one buyer currency for the whole basket
    /// (<c>CheckoutEndpoints.ResolveBuyerCurrency</c>), so more than one arriving here is a bug
    /// upstream — and a bug upstream on the money path must not open a session.
    /// </remarks>
    private static string SingleCurrency(IReadOnlyList<CheckoutLine> lines)
    {
        var currencies = lines
            .Select(line => (line.Currency ?? "GBP").ToUpperInvariant())
            .Distinct(StringComparer.Ordinal)
            .ToArray();
        if (currencies.Length > 1)
        {
            throw new ArgumentException(
                $"A checkout is billed in exactly one currency; got [{string.Join(", ", currencies)}].",
                nameof(lines));
        }
        return currencies[0].ToLowerInvariant();
    }

    /// <summary>
    /// Everything about a checkout session that is not the surface it renders on. Shared by the
    /// hosted and embedded paths so a change to tax, metadata or the statement descriptor cannot
    /// apply to one and not the other.
    /// </summary>
    private SessionCreateOptions BuildSessionOptions(IReadOnlyList<CheckoutLine> lines, string? buyerEmail)
    {
        EnsureStripeConfigured();

        if (lines.Count == 0)
        {
            throw new ArgumentException("A checkout needs at least one pack.", nameof(lines));
        }
        if (lines.Count > MaxCheckoutLines)
        {
            throw new ArgumentException(
                $"A checkout carries at most {MaxCheckoutLines} packs; got {lines.Count}.", nameof(lines));
        }

        var currency = SingleCurrency(lines);
        var metadata = BuildCheckoutMetadata(lines);

        return new SessionCreateOptions
        {
            LineItems = [.. lines.Select(line => new SessionLineItemOptions
            {
                Price = line.ProviderPriceId,
                Quantity = 1,
            })],
            // The buyer's currency, not the Price object's. A Price carries its base currency
            // plus `currency_options` for the others it can be sold in (minted together in
            // bridge.py), and this is what selects between them. It is only ever set to a
            // non-GBP value when the caller has verified every pack in the basket carries that
            // currency's amount — Stripe rejects a session in a currency the Price has no
            // option for, which is a refusal to sell, not a mispriced sale.
            Currency = currency,
            Mode = "payment",
            CustomerEmail = buyerEmail,
            // P0-1 — stamp the pack ids so the inbound webhook (ExtractItemsAsync) can resolve
            // which packs were bought and grant the entitlements. Without this every payment
            // is paid-but-unfulfilled.
            Metadata = metadata,
            // Propagate the same metadata onto the resulting PaymentIntent so it is also
            // visible on charge.* / dispute events used by the refund handler.
            PaymentIntentData = new SessionPaymentIntentDataOptions
            {
                Metadata = new Dictionary<string, string>(metadata, StringComparer.Ordinal),
                // Brand the buyer's card statement — see StatementDescriptorSuffix.
                StatementDescriptorSuffix = StatementDescriptorSuffix,
            },
            // P5 — Stripe Tax: automatic VAT/sales-tax calculation at checkout.
            // Requires Stripe Tax + a head-office address configured in the Stripe
            // dashboard (https://dashboard.stripe.com/settings/tax). When active, the
            // buyer sees the tax-inclusive total and the webhook session includes
            // total_details.amount_tax for the SalesAudit. Defaults ON (live intent).
            // Set the Stripe AutomaticTax config key to the string false to turn it off
            // for a test account that has no tax or head-office address configured yet.
            AutomaticTax = new SessionAutomaticTaxOptions
            {
                Enabled = !string.Equals(config["Stripe:AutomaticTax"], "false", StringComparison.OrdinalIgnoreCase),
            },
            // Billing address collection is deliberately left at Stripe's default rather than
            // set here: automatic tax REQUIRES an address, and Stripe's default already collects
            // one when AutomaticTax is on. Pinning it to a literal would be a second, silent
            // switch that could contradict the tax setting above.
        };
    }

    /// <summary>
    /// Whether the Stripe account THIS deployment bills through can charge that price.
    /// </summary>
    /// <remarks>
    /// Resolves the price with our own key, which is the whole point: a price id minted by a
    /// different account (a publisher still holding a sandbox key, say) is well-formed and
    /// completely unbillable here, and no amount of inspecting the string reveals that. Stripe
    /// answers "No such price" and we decline to list.
    /// <para>
    /// An inactive price is treated as unbillable too — Stripe refuses it at session creation,
    /// so listing it would produce the same dead buy button by a different route.
    /// </para>
    /// <para>
    /// A transport failure returns false rather than throwing: this gates whether a pack goes on
    /// sale, and the safe answer when we cannot confirm billability is not to list. The publish
    /// still succeeds and the pack is stored unlisted, so a retry lists it once Stripe answers.
    /// </para>
    /// </remarks>
    public async Task<bool> CanBillPriceAsync(string providerPriceId, CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(providerPriceId)
            || providerPriceId.StartsWith("price_stub", StringComparison.Ordinal))
        {
            return false;
        }

        EnsureStripeConfigured();
        try
        {
            var price = await new PriceService().GetAsync(providerPriceId, cancellationToken: ct).ConfigureAwait(false);
            return price is { Active: true };
        }
        catch (StripeException ex)
        {
            logger.LogWarning(
                ex, "Stripe cannot bill price {PriceId}; refusing to list the pack.", providerPriceId);
            return false;
        }
    }

    /// <summary>
    /// The metadata that lets the inbound webhook reconstruct the basket.
    /// </summary>
    /// <remarks>
    /// <c>pack_ids</c> and <c>price_ids</c> are parallel CSVs: entry i of one describes the same
    /// line as entry i of the other. The pairing is explicit rather than positional against
    /// whatever order Stripe hands back its line items, which is not a documented guarantee.
    /// <para>
    /// <c>pack_id</c> (singular) is still written for a one-pack basket. Anything reading Stripe
    /// data outside this codebase — a Dashboard view, an export, a support query — has only ever
    /// seen that key, and every existing session in flight uses it.
    /// </para>
    /// </remarks>
    internal static Dictionary<string, string> BuildCheckoutMetadata(IReadOnlyList<CheckoutLine> lines)
    {
        var metadata = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["pack_ids"] = string.Join(",", lines.Select(l => l.PackId)),
            ["price_ids"] = string.Join(",", lines.Select(l => l.ProviderPriceId)),
        };
        if (lines.Count == 1)
        {
            metadata["pack_id"] = lines[0].PackId;
        }
        return metadata;
    }

    // Stripe expands the literal token {CHECKOUT_SESSION_ID} in the success URL. Applied here
    // rather than by the caller because the token is Stripe-specific — Paddle would receive it
    // verbatim and hand the buyer a broken link.
    private static string AppendSessionIdTemplate(string successUrl)
        => DeliveryUrls.AppendSessionIdTemplate(successUrl);

    // Resolve a checkout-session id to the transaction id stamped on the Order. Deliberately
    // refuses to resolve an unpaid session: the session id travels in the buyer's URL, so
    // treating it as proof of purchase without re-checking payment status with Stripe would
    // let an abandoned checkout mint a download link.
    public async Task<string?> ResolvePaidTransactionIdAsync(string sessionId, CancellationToken ct)
    {
        EnsureStripeConfigured();

        try
        {
            var session = await new SessionService().GetAsync(sessionId, cancellationToken: ct)
                .ConfigureAwait(false);

            if (!string.Equals(session.PaymentStatus, "paid", StringComparison.Ordinal))
            {
                return null;
            }

            // Must match how the webhook records the Order: session.PaymentIntentId ?? session.Id.
            return session.PaymentIntentId ?? session.Id;
        }
        catch (StripeException ex)
        {
            logger.LogWarning(ex, "Could not resolve Stripe checkout session {SessionId}.", sessionId);
            return null;
        }
    }

    private void EnsureStripeConfigured()
    {
        if (string.IsNullOrEmpty(StripeConfiguration.ApiKey))
        {
            var apiKey = config["Stripe:ApiKey"];
            if (!string.IsNullOrEmpty(apiKey))
            {
                StripeConfiguration.ApiKey = apiKey;
            }
            else
            {
                logger.LogError("Stripe:ApiKey is missing.");
            }
        }
    }
}
