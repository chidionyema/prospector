using System.Security.Cryptography;
using System.Text;
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

builder.Services.AddSingleton<ITokenGenerator, TokenGenerator>();
builder.Services.AddScoped<FulfilmentService>();
builder.Services.AddSingleton<IContentStorage, R2ContentStorage>();
builder.Services.AddHttpClient<IEmailSender, PostmarkEmailSender>();

builder.Services.AddKeyedScoped<IPaymentProvider, PaddleProvider>("paddle");
builder.Services.AddKeyedScoped<IPaymentProvider, StripeProvider>("stripe");
builder.Services.AddHostedService<MoneyRailConfigGate>();

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();

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

    pack.PaymentProvider = request.PaymentProvider;
    pack.ProviderProductId = request.ProviderProductId;
    pack.ProviderPriceId = request.ProviderPriceId;

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

app.MapWebhookEndpoints();
app.MapDeliveryEndpoints();

await app.RunAsync().ConfigureAwait(false);
