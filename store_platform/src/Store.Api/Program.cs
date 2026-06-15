using Microsoft.EntityFrameworkCore;
using Store.Api.Endpoints;
using Store.Api.Contracts;
using Store.Catalog.Domain;
using Store.Catalog.Persistence;

var builder = WebApplication.CreateBuilder(args);

// Add services to the container.
var connectionString = builder.Configuration.GetConnectionString("DefaultConnection") ?? "Data Source=store.db";
builder.Services.AddDbContext<StoreDbContext>(options =>
    options.UseSqlite(connectionString));

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();

var app = builder.Build();

// Ensure database is created/migrated
using (var scope = app.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<StoreDbContext>();
    await db.Database.EnsureCreatedAsync().ConfigureAwait(false);
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
            p.PaddlePriceId
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
            pack.PaddlePriceId,
            pack.DossierRef
        })
        : Results.NotFound();
})
.WithName("GetPackDetails")
.WithOpenApi();

// --- INTERNAL/ENGINE ENDPOINTS ---

app.MapPost("/internal/catalog", async (PublishRequest request, StoreDbContext db) =>
{
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

    pack.PaddleProductId = request.PaddleProductId;
    pack.PaddlePriceId = request.PaddlePriceId;
    pack.IsListed = request.IsListed;

    await db.SaveChangesAsync().ConfigureAwait(false);
    return Results.Ok(pack);
})
.WithName("PublishPack")
.WithOpenApi();

// --- WEBHOOK ENDPOINTS ---

app.MapWebhookEndpoints();

await app.RunAsync().ConfigureAwait(false);
