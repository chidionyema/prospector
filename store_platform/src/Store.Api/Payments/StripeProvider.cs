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

            return new WebhookVerifyResult(true, BuildTransaction(session, stripeEvent), null);
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

    private static PaymentTransaction BuildTransaction(Session session, Stripe.Event stripeEvent) =>
        new(
            Provider: "stripe",
            TransactionId: session.PaymentIntentId ?? session.Id,
            BuyerEmail: session.CustomerDetails?.Email ?? session.CustomerEmail ?? "",
            Currency: session.Currency?.ToUpperInvariant() ?? "GBP",
            Country: session.CustomerDetails?.Address?.Country ?? "",
            TotalAmountPence: session.AmountTotal ?? 0,
            OccurredAt: stripeEvent.Created,
            Items: ExtractItems(session));

    private static List<PurchasedItem> ExtractItems(Session session)
    {
        var items = new List<PurchasedItem>();
        if (session.Metadata.TryGetValue("pack_id", out var packId))
        {
            items.Add(new PurchasedItem(packId, session.AmountTotal ?? 0));
        }
        return items;
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

    public async Task<CheckoutHandle> CreateCheckoutAsync(string packId, string providerPriceId, string? buyerEmail, string successUrl, string cancelUrl, CancellationToken ct)
    {
        EnsureStripeConfigured();

        var options = new SessionCreateOptions
        {
            LineItems =
            [
                new SessionLineItemOptions
                {
                    Price = providerPriceId,
                    Quantity = 1,
                },
            ],
            Mode = "payment",
            CustomerEmail = buyerEmail,
            // Stripe substitutes the literal {CHECKOUT_SESSION_ID} template on redirect. The
            // storefront uses it to resolve the buyer's entitlement and render a real download
            // link on the success page, so fulfilment no longer depends on an email arriving.
            SuccessUrl = AppendSessionIdTemplate(successUrl),
            CancelUrl = cancelUrl,
            // P0-1 — stamp the pack id so the inbound webhook (ExtractItems) can resolve
            // which pack was bought and grant the entitlement. Without this every payment
            // is paid-but-unfulfilled.
            Metadata = new Dictionary<string, string>(StringComparer.Ordinal)
            {
                ["pack_id"] = packId,
            },
            // Propagate the same metadata onto the resulting PaymentIntent so it is also
            // visible on charge.* / dispute events used by the refund handler.
            PaymentIntentData = new SessionPaymentIntentDataOptions
            {
                Metadata = new Dictionary<string, string>(StringComparer.Ordinal)
                {
                    ["pack_id"] = packId,
                },
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
        };

        var service = new SessionService();
        var session = await service.CreateAsync(options, cancellationToken: ct).ConfigureAwait(false);

        return new CheckoutHandle(session.Url, session.ClientSecret);
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
