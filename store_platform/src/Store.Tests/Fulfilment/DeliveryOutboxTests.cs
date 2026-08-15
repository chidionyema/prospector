using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging.Abstractions;
using Store.Api.Services;
using Store.Catalog.Domain;
using Store.Catalog.Persistence;

namespace Store.Tests.Fulfilment;

/// <summary>
/// The paid-without-delivery window, closed.
///
/// Before the outbox, the magic-link email was dispatched inline in the webhook handler AFTER the
/// fulfilment commit and outside it. Anything that interrupted the process in between -- a deploy
/// SIGTERM (this API runs ONE machine on SQLite, so every deploy is exactly that), a crash, a
/// Mailjet blip -- lost the buyer's link permanently, because the provider's retry hits the webhook
/// dedup short-circuit and returns ALREADY_PROCESSED without ever reaching the send.
///
/// These tests reproduce that window literally: fulfil, send NOTHING, then run the drain as a
/// fresh process would, and require the link to go out. Real SQLite, not the EF InMemory provider,
/// so the unique index on EntitlementId is actually enforced.
/// </summary>
public sealed class DeliveryOutboxTests : IDisposable
{
    private readonly SqliteConnection _connection;
    private readonly DbContextOptions<StoreDbContext> _options;

    public DeliveryOutboxTests()
    {
        _connection = new SqliteConnection("Data Source=:memory:");
        _connection.Open();
        _options = new DbContextOptionsBuilder<StoreDbContext>()
            .UseSqlite(_connection)
            .Options;
        using var ctx = new StoreDbContext(_options);
        ctx.Database.EnsureCreated();
    }

    [Fact]
    public async Task Fulfilment_EnqueuesTheDelivery_InTheSameCommitAsTheEntitlement()
    {
        await SeedPackAsync("pack-1", "prod-1", "content/pack-1.zip");

        await FulfilAsync(Txn("txn-1", new PurchasedItem("prod-1", 3000)));

        using var verify = NewContext();
        var entitlement = await verify.Entitlements.SingleAsync();
        var pending = await verify.PendingDeliveries.SingleAsync();

        Assert.Equal(entitlement.Id, pending.EntitlementId);
        Assert.Equal("pack-1", pending.PackId);
        Assert.Equal("buyer@example.com", pending.BuyerEmail);
        Assert.Equal(entitlement.GrantToken, pending.GrantToken);
        Assert.Null(pending.SentAt);   // owed, not yet delivered
        Assert.Equal(0, pending.Attempts);
    }

    /// <summary>
    /// THE regression this whole mechanism exists for. The process dies between the commit and
    /// the send; a new one starts and must deliver anyway, with no help from the provider.
    /// </summary>
    [Fact]
    public async Task ALinkOwedWhenTheProcessDied_IsSentByTheNextDrain()
    {
        await SeedPackAsync("pack-1", "prod-1", "content/pack-1.zip");
        await FulfilAsync(Txn("txn-1", new PurchasedItem("prod-1", 3000)));
        // ... and nothing sends it. This is the restart window.

        var sender = new RecordingEmailSender();
        var result = await DrainAsync(sender);

        Assert.Equal(1, result.Sent);
        var (email, title, url) = Assert.Single(sender.Sent);
        Assert.Equal("buyer@example.com", email);
        Assert.Equal("pack-1", title);   // resolved from the catalogue, not the id

        using var verify = NewContext();
        var pending = await verify.PendingDeliveries.SingleAsync();
        Assert.EndsWith($"/orders/{pending.GrantToken}", url, StringComparison.Ordinal);
        Assert.NotNull(pending.SentAt);
    }

    [Fact]
    public async Task ASentDelivery_IsNotSentAgainByALaterDrain()
    {
        await SeedPackAsync("pack-1", "prod-1", "content/pack-1.zip");
        await FulfilAsync(Txn("txn-1", new PurchasedItem("prod-1", 3000)));

        var sender = new RecordingEmailSender();
        await DrainAsync(sender);
        var second = await DrainAsync(sender);

        Assert.Equal(0, second.Sent);
        Assert.Single(sender.Sent);
    }

    [Fact]
    public async Task AFailedSend_StaysQueuedAndIsDeliveredOnTheNextDrain()
    {
        await SeedPackAsync("pack-1", "prod-1", "content/pack-1.zip");
        await FulfilAsync(Txn("txn-1", new PurchasedItem("prod-1", 3000)));

        var failing = new RecordingEmailSender { Succeed = false };
        var first = await DrainAsync(failing);
        Assert.Equal(0, first.Sent);
        Assert.Equal(1, first.Failed);

        using (var afterFailure = NewContext())
        {
            var pending = await afterFailure.PendingDeliveries.SingleAsync();
            Assert.Null(pending.SentAt);
            Assert.Equal(1, pending.Attempts);
            Assert.NotNull(pending.LastError);
        }

        var working = new RecordingEmailSender();
        Assert.Equal(1, (await DrainAsync(working)).Sent);
        Assert.Single(working.Sent);
    }

    /// <summary>
    /// A sender that throws must not take the rest of the batch down with it -- one bad address
    /// stranding every other buyer's link would recreate the failure at batch scale.
    /// </summary>
    [Fact]
    public async Task AThrowingSender_IsRecordedAsAFailedAttemptNotAnUnhandledException()
    {
        await SeedPackAsync("pack-1", "prod-1", "content/pack-1.zip");
        await FulfilAsync(Txn("txn-1", new PurchasedItem("prod-1", 3000)));

        var result = await DrainAsync(new ThrowingEmailSender());

        Assert.Equal(1, result.Failed);
        using var verify = NewContext();
        var pending = await verify.PendingDeliveries.SingleAsync();
        Assert.Equal(1, pending.Attempts);
        Assert.Contains("boom", pending.LastError, StringComparison.Ordinal);
    }

    /// <summary>
    /// Missing delivery config must not burn attempts. The obligation is real and the
    /// configuration is what is broken; retiring the row here would lose the link for a fault
    /// that has nothing to do with it.
    /// </summary>
    [Fact]
    public async Task AnUnconfiguredSender_LeavesTheDeliveryQueuedWithoutConsumingAnAttempt()
    {
        await SeedPackAsync("pack-1", "prod-1", "content/pack-1.zip");
        await FulfilAsync(Txn("txn-1", new PurchasedItem("prod-1", 3000)));

        var result = await DrainAsync(new RecordingEmailSender { Configured = false });

        Assert.Equal(0, result.Sent);
        Assert.Equal(1, result.Skipped);
        using var verify = NewContext();
        var pending = await verify.PendingDeliveries.SingleAsync();
        Assert.Null(pending.SentAt);
        Assert.Equal(0, pending.Attempts);
    }

    [Fact]
    public async Task ADeliveryThatExhaustsItsAttempts_DropsOutOfTheDrain()
    {
        await SeedPackAsync("pack-1", "prod-1", "content/pack-1.zip");
        await FulfilAsync(Txn("txn-1", new PurchasedItem("prod-1", 3000)));

        var failing = new RecordingEmailSender { Succeed = false };
        Assert.Equal(1, (await DrainAsync(failing, maxAttempts: 2)).Failed);
        Assert.Equal(1, (await DrainAsync(failing, maxAttempts: 2)).Failed);

        // Third pass: the row is past its attempt ceiling and is no longer picked up.
        var third = await DrainAsync(failing, maxAttempts: 2);
        Assert.Equal(0, third.Failed);
        Assert.Equal(0, third.Sent);
        Assert.Equal(2, failing.Attempted);
    }

    /// <summary>An unfulfillable item creates no entitlement, so it must create no obligation.</summary>
    [Fact]
    public async Task AnUnknownProduct_EnqueuesNothing()
    {
        await FulfilAsync(Txn("txn-1", new PurchasedItem("ghost", 3000)));

        using var verify = NewContext();
        Assert.Equal(0, await verify.PendingDeliveries.CountAsync());
    }

    private async Task FulfilAsync(PaymentTransaction txn)
    {
        using var ctx = NewContext();
        var svc = new FulfilmentService(ctx, new TokenGenerator());
        await svc.FulfilAsync(txn);
    }

    private async Task<DeliveryDrainResult> DrainAsync(IEmailSender sender, int maxAttempts = 10)
    {
        using var ctx = NewContext();
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>(StringComparer.Ordinal)
            {
                ["Store:PublicUrl"] = "https://api.example.com/",
                ["Delivery:MaxAttempts"] = maxAttempts.ToString(System.Globalization.CultureInfo.InvariantCulture),
            })
            .Build();
        var drain = new DeliveryDrain(ctx, sender, config, NullLogger<DeliveryDrain>.Instance);
        return await drain.DrainAsync();
    }

    private async Task SeedPackAsync(string id, string productId, string? contentKey)
    {
        using var ctx = NewContext();
        ctx.Packs.Add(new Pack
        {
            Id = id,
            Title = id,
            OneLine = "x",
            DossierRef = "d",
            PaymentProvider = "paddle",
            ProviderProductId = productId,
            ContentKey = contentKey,
            ContentVersion = 1,
            PricePence = 0,
        });
        await ctx.SaveChangesAsync();
    }

    private static PaymentTransaction Txn(string id, params PurchasedItem[] items) =>
        new("paddle", id, "buyer@example.com", "GBP", "GB", 3000,
            new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc), items);

    private StoreDbContext NewContext() => new(_options);

    public void Dispose()
    {
        _connection.Dispose();
        GC.SuppressFinalize(this);
    }

    private sealed class RecordingEmailSender : IEmailSender
    {
        public bool Succeed { get; init; } = true;
        public bool Configured { get; init; } = true;
        public int Attempted { get; private set; }
        public List<(string Email, string Title, string Url)> Sent { get; } = [];

        public bool IsConfigured => Configured;

        public Task<bool> SendDownloadLinkAsync(string toEmail, string packTitle, string orderUrl)
        {
            Attempted++;
            if (Succeed)
            {
                Sent.Add((toEmail, packTitle, orderUrl));
            }
            return Task.FromResult(Succeed);
        }
    }

    private sealed class ThrowingEmailSender : IEmailSender
    {
        public bool IsConfigured => true;

        public Task<bool> SendDownloadLinkAsync(string toEmail, string packTitle, string orderUrl) =>
            throw new InvalidOperationException("boom");
    }
}
