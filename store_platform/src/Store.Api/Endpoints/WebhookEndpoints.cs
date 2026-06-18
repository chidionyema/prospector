using Microsoft.EntityFrameworkCore;
using Store.Api.Payments;
using Store.Api.Services;
using Store.Catalog.Domain;
using Store.Catalog.Persistence;

namespace Store.Api.Endpoints;

public static class WebhookEndpoints
{
    public static void MapWebhookEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapPost("/webhooks/{provider}", HandleWebhook);
        app.MapPost("/webhooks/paddle", (
            HttpRequest request,
            IConfiguration config,
            ILogger<Program> logger,
            FulfilmentService fulfilmentService,
            StoreDbContext db,
            IEmailSender emailSender,
            IServiceProvider sp) => HandleWebhook("paddle", request, config, logger, fulfilmentService, db, emailSender, sp));
    }

    private static async Task<IResult> HandleWebhook(
        string provider,
        HttpRequest request,
        IConfiguration config,
        ILogger<Program> logger,
        FulfilmentService fulfilmentService,
        StoreDbContext db,
        IEmailSender emailSender,
        IServiceProvider sp)
    {
        var paymentProvider = sp.GetKeyedService<IPaymentProvider>(provider);
        if (paymentProvider is null)
        {
            return Results.NotFound();
        }

        using var reader = new StreamReader(request.Body);
        var rawBody = await reader.ReadToEndAsync().ConfigureAwait(false);

        var result = await paymentProvider.VerifyAndParseAsync(request, rawBody, config, logger).ConfigureAwait(false);

        if (!result.Verified)
        {
            return HandleVerifyFailure(result);
        }

        var txn = result.Transaction!;

        // --- DEDUP LAYER (P2) ---
        if (await RegisterWebhookEventAsync(db, provider, txn, result.Reason, rawBody).ConfigureAwait(false))
        {
            return Results.Ok(new { status = "ALREADY_PROCESSED", eventId = txn.TransactionId });
        }

        var outcome = await fulfilmentService.FulfilAsync(txn).ConfigureAwait(false);
        if (outcome.AlreadyProcessed)
        {
            return Results.Ok(new { status = "ALREADY_PROCESSED" });
        }

        if (outcome.Unfulfilled.Count > 0)
        {
            logger.LogError("PAID-WITHOUT-FULFILMENT for {TransactionId}: {Items}",
                txn.TransactionId, string.Join(", ", outcome.Unfulfilled));
        }

        var storeUrl = config["Store:PublicUrl"] ?? Environment.GetEnvironmentVariable("STORE_PUBLIC_URL");
        await DispatchEmailsAsync(outcome.EntitlementsCreated, db, emailSender, storeUrl, logger)
            .ConfigureAwait(false);

        return Results.Ok(new
        {
            status = "PROCESSED",
            entitlements = outcome.EntitlementsCreated.Count,
            unfulfilled = outcome.Unfulfilled,
        });
    }

    // Records the inbound webhook for dedup. Returns true if this event was already
    // processed (caller short-circuits with ALREADY_PROCESSED). The WebhookEvent is only
    // staged here — the actual SaveChangesAsync (and thus any unique-constraint race) happens
    // downstream in FulfilmentService.CommitAsync, where the duplicate is caught. A try/catch
    // around Add() here would be dead code: Add() never touches the database.
    private static async Task<bool> RegisterWebhookEventAsync(
        StoreDbContext db, string provider, PaymentTransaction txn, string? reason, string rawBody)
    {
        if (await WebhookAlreadyProcessedAsync(db, provider, txn.TransactionId).ConfigureAwait(false))
        {
            return true;
        }

        db.WebhookEvents.Add(new WebhookEvent
        {
            Provider = provider,
            ProviderEventId = txn.TransactionId,
            EventType = reason ?? "completed",
            RawPayload = rawBody
        });

        return false;
    }

    private static IResult HandleVerifyFailure(WebhookVerifyResult result)
    {
        if (string.Equals(result.Reason, "secret-not-configured", StringComparison.Ordinal))
        {
            return Results.StatusCode(StatusCodes.Status503ServiceUnavailable);
        }
        if (result.Ignored)
        {
            return Results.Ok(new { status = "IGNORED", eventType = result.Reason });
        }
        return Results.BadRequest(result.Reason ?? "Invalid signature");
    }

    private static Task<bool> WebhookAlreadyProcessedAsync(StoreDbContext db, string provider, string eventId) =>
        db.WebhookEvents.AnyAsync(e => e.Provider == provider && e.ProviderEventId == eventId);

    private static async Task DispatchEmailsAsync(
        IReadOnlyList<Entitlement> entitlements,
        StoreDbContext db,
        IEmailSender emailSender,
        string? storeUrl,
        ILogger logger)
    {
        if (entitlements.Count == 0 || string.IsNullOrEmpty(storeUrl) || !emailSender.IsConfigured)
        {
            return;
        }

        var baseUrl = storeUrl.TrimEnd('/');
        foreach (var ent in entitlements)
        {
            var title = await db.Packs
                .Where(p => p.Id == ent.PackId)
                .Select(p => p.Title)
                .FirstOrDefaultAsync()
                .ConfigureAwait(false) ?? ent.PackId;

            var orderUrl = $"{baseUrl}/orders/{ent.GrantToken}";
            var sent = await emailSender.SendDownloadLinkAsync(ent.BuyerEmail, title, orderUrl)
                .ConfigureAwait(false);
            if (!sent)
            {
                logger.LogWarning(
                    "Magic-link email not sent for {PackId} to {Email}; link can be re-issued.",
                    ent.PackId, ent.BuyerEmail);
            }
        }
    }
}
