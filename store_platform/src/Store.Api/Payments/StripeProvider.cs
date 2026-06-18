using Stripe;
using Stripe.Checkout;
using Store.Api.Services;

namespace Store.Api.Payments;

public sealed class StripeProvider(IConfiguration config, ILogger<StripeProvider> logger) : IPaymentProvider
{
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
            SuccessUrl = successUrl,
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
            },
            // P5 — Stripe Tax: automatic VAT/sales-tax calculation at checkout.
            // Requires Stripe Tax to be enabled in the Stripe dashboard. When active,
            // the buyer sees the tax-inclusive total; the webhook session includes
            // total_details.amount_tax for the SalesAudit.
            AutomaticTax = new SessionAutomaticTaxOptions { Enabled = true },
        };

        var service = new SessionService();
        var session = await service.CreateAsync(options, cancellationToken: ct).ConfigureAwait(false);

        return new CheckoutHandle(session.Url, session.ClientSecret);
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
