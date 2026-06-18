using System.Security.Cryptography;
using System.Text;
using System.Threading.RateLimiting;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.EntityFrameworkCore;
using Store.Api.Endpoints;
using Store.Api.Contracts;
using Store.Catalog.Domain;
using Store.Catalog.Persistence;
using Store.Api.Services;
using Store.Api.Payments;

var builder = WebApplication.CreateBuilder(args);

// Add services to the container.
var connectionString = builder.Configuration.GetConnectionString("DefaultConnection") ?? "Data Source=store.db";
builder.Services.AddDbContext<StoreDbContext>(options =>
    options.UseSqlite(connectionString));

// CORS — locked to the storefront origin so the browser accepts cross-origin
// requests from the Next.js storefront to this API. Configure via Store:AllowedOrigin
// or STORE_ALLOWED_ORIGIN env var. Defaults to localhost:3000 for development.
var allowedOrigin = builder.Configuration["Store:AllowedOrigin"]
    ?? Environment.GetEnvironmentVariable("STORE_ALLOWED_ORIGIN")
    ?? "http://localhost:3000";
builder.Services.AddCors(options =>
{
    options.AddDefaultPolicy(policy =>
        policy.WithOrigins(allowedOrigin)
              .AllowAnyHeader()
              .AllowAnyMethod()
              .AllowCredentials());
});

builder.Services.AddSingleton<ITokenGenerator, TokenGenerator>();
builder.Services.AddScoped<FulfilmentService>();
builder.Services.AddSingleton<IContentStorage, R2ContentStorage>();
builder.Services.AddHttpClient<IEmailSender, PostmarkEmailSender>();

builder.Services.AddKeyedScoped<IPaymentProvider, PaddleProvider>("paddle");
builder.Services.AddKeyedScoped<IPaymentProvider, StripeProvider>("stripe");
builder.Services.AddHostedService<MoneyRailConfigGate>();

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();

// P1-7 — rate limiting. A global per-IP fixed-window limiter caps abusive bursts (token
// guessing on /download, checkout spam). Webhooks are exempt: providers retry on non-2xx
// and a 429'd webhook would drop fulfilment. Limits are overridable via RateLimiting:*.
var rlPermit = builder.Configuration.GetValue<int?>("RateLimiting:PermitPerMinute") ?? 120;
builder.Services.AddRateLimiter(options =>
{
    options.RejectionStatusCode = StatusCodes.Status429TooManyRequests;
    options.GlobalLimiter = PartitionedRateLimiter.Create<HttpContext, string>(httpContext =>
    {
        // Webhooks must never be throttled — exempt them with a no-limit partition.
        var path = httpContext.Request.Path.Value ?? string.Empty;
        if (path.StartsWith("/webhooks", StringComparison.OrdinalIgnoreCase))
        {
            return RateLimitPartition.GetNoLimiter("webhooks");
        }

        var clientKey = httpContext.Connection.RemoteIpAddress?.ToString() ?? "unknown";
        return RateLimitPartition.GetFixedWindowLimiter(clientKey, _ => new FixedWindowRateLimiterOptions
        {
            PermitLimit = rlPermit,
            Window = TimeSpan.FromMinutes(1),
            QueueLimit = 0,
        });
    });
});

var app = builder.Build();

// Apply EF migrations at startup. MigrateAsync (not EnsureCreated) so new tables
// (Orders, Entitlements) and future schema changes land on an existing database.
using (var scope = app.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<StoreDbContext>();
    await db.Database.MigrateAsync().ConfigureAwait(false);
}

// Configure the HTTP request pipeline.
if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

// CORS middleware — must come between routing and endpoints.
app.UseCors();

// P1-7 — rate limiter must run before endpoints so throttled requests short-circuit.
app.UseRateLimiter();

// --- PUBLIC CATALOG ENDPOINTS ---

app.MapGet("/catalog", async (StoreDbContext db) =>
{
    return await db.Packs
        .Where(p => p.IsListed)
        .OrderByDescending(p => p.CreatedAt)
        .Select(p => new {
            p.Id,
            p.Title,
            p.OneLine,
            Price = Money.ToDisplayString(p.PricePence, "£"),
            p.PaymentProvider,
            p.ProviderPriceId
        })
        .ToListAsync()
        .ConfigureAwait(false);
})
.WithName("GetCatalog")
.WithOpenApi();

app.MapGet("/catalog/{id}", async (string id, StoreDbContext db) =>
{
    var pack = await db.Packs.FindAsync(id).ConfigureAwait(false);
    return pack is not null
        ? Results.Ok(new {
            pack.Id,
            pack.Title,
            pack.OneLine,
            Price = Money.ToDisplayString(pack.PricePence, "£"),
            pack.PaymentProvider,
            pack.ProviderPriceId,
            pack.DossierRef
        })
        : Results.NotFound();
})
.WithName("GetPackDetails")
.WithOpenApi();

// --- INTERNAL/ENGINE ENDPOINTS ---

app.MapPost("/internal/catalog", async (PublishRequest request, HttpRequest http, StoreDbContext db, IConfiguration config) =>
{
    // Authenticate the engine→store publish call. Fail closed if no key is configured
    // (an unauthenticated internal endpoint would let anyone publish to the catalogue).
    var expectedKey = config["Store:InternalApiKey"]
        ?? Environment.GetEnvironmentVariable("STORE_INTERNAL_API_KEY");
    if (string.IsNullOrEmpty(expectedKey))
    {
        return Results.Problem("Internal API key not configured", statusCode: StatusCodes.Status503ServiceUnavailable);
    }
    var providedKey = http.Headers["X-Internal-Key"].ToString();
    if (string.IsNullOrEmpty(providedKey) ||
        !CryptographicOperations.FixedTimeEquals(
            Encoding.UTF8.GetBytes(providedKey),
            Encoding.UTF8.GetBytes(expectedKey)))
    {
        return Results.Unauthorized();
    }

    var pack = await db.Packs.FindAsync(request.Id).ConfigureAwait(false);
    if (pack == null)
    {
        pack = new Pack
        {
            Id = request.Id,
            Title = request.Title,
            OneLine = request.OneLine,
            DossierRef = request.DossierRef,
            PricePence = request.PricePence ?? Money.DefaultPackPricePence
        };
        db.Packs.Add(pack);
    }
    else
    {
        pack.Title = request.Title;
        pack.OneLine = request.OneLine;
        pack.DossierRef = request.DossierRef;
    }

    // PaymentProvider defaults to "paddle" for backward compatibility with
    // engine publishes that only send the legacy PaddleProductId/PaddlePriceId.
    pack.PaymentProvider = request.PaymentProvider
        ?? (request.PaddleProductId is not null ? "paddle" : null)
        ?? "paddle";
    pack.ProviderProductId = request.ProviderProductId ?? request.PaddleProductId;
    pack.ProviderPriceId = request.ProviderPriceId ?? request.PaddlePriceId;

    // Content metadata (set by the engine after it uploads the deliverable to R2).
    if (request.ContentKey is not null)
    {
        pack.ContentKey = request.ContentKey;
    }
    if (request.ContentHash is not null)
    {
        pack.ContentHash = request.ContentHash;
    }
    if (request.ContentVersion is { } version)
    {
        pack.ContentVersion = version;
    }

    // List-only-after-upload: a pack may only go live once it has deliverable content.
    // Selling something we cannot deliver is the cardinal sin of this layer.
    pack.IsListed = request.IsListed && !string.IsNullOrEmpty(pack.ContentKey);

    await db.SaveChangesAsync().ConfigureAwait(false);
    return Results.Ok(pack);
})
.WithName("PublishPack")
.WithOpenApi();

// --- WEBHOOK + DELIVERY ENDPOINTS ---

// --- CHECKOUT ENDPOINT (P4/P7 — provider-agnostic, hot-reloaded) ---
// The provider for NEW checkouts is determined by the runtime config
// `payments:active_provider` (P7 — seamless switch, no redeploy). For
// packs published before the switch, the pack's stored PaymentProvider is
// honoured as a fallback so the buyer's checkout always succeeds.
app.MapPost("/packs/{id}/checkout", async (
    string id,
    StoreDbContext db,
    IServiceProvider sp,
    IConfiguration config,
    HttpRequest request) =>
{
    var pack = await db.Packs.FindAsync(id).ConfigureAwait(false);
    if (pack is null || !pack.IsListed)
    {
        return Results.NotFound();
    }

    // P7 — runtime active_provider (hot-reloaded) takes precedence for new checkouts
    // and falls back to the pack's stored provider so legacy packs still work.
    var runtimeProvider = config["payments:active_provider"];
    var provider = !string.IsNullOrEmpty(runtimeProvider) ? runtimeProvider : (pack.PaymentProvider ?? "paddle");
    var paymentProvider = sp.GetKeyedService<IPaymentProvider>(provider);
    if (paymentProvider is null)
    {
        return Results.Problem(
            $"Payment provider '{provider}' is not registered.",
            statusCode: StatusCodes.Status503ServiceUnavailable);
    }

    string? buyerEmail = null;
    if (request.HasJsonContentType())
    {
        try
        {
            var body = await request.ReadFromJsonAsync<CheckoutRequest>().ConfigureAwait(false);
            buyerEmail = body?.Email;
        }
        catch
        {
            // Buyer email is optional; proceed with null if parse fails.
        }
    }

    var storeUrl = config["Store:PublicUrl"] ?? Environment.GetEnvironmentVariable("STORE_PUBLIC_URL")
        ?? $"{request.Scheme}://{request.Host}";
    var baseUrl = storeUrl.TrimEnd('/');

    var handle = await paymentProvider.CreateCheckoutAsync(
        id,
        pack.ProviderPriceId ?? "",
        buyerEmail,
        $"{baseUrl}/orders/success?pack={id}",
        $"{baseUrl}/pack/{id}",
        CancellationToken.None).ConfigureAwait(false);

    return Results.Ok(new { url = handle.Url });
})
.WithName("CreateCheckout")
.WithOpenApi();

app.MapWebhookEndpoints();
app.MapDeliveryEndpoints();

await app.RunAsync().ConfigureAwait(false);
