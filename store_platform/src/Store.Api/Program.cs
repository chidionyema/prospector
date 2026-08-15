using System.Globalization;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading.RateLimiting;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.HttpOverrides;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.EntityFrameworkCore;
using Store.Api.Auth;
using Store.Api.Endpoints;
using Store.Api.Contracts;
using Store.Api.Infrastructure;
using Store.Catalog.Domain;
using Store.Catalog.Persistence;
using Store.Api.Services;
using Store.Api.Payments;
using Crux.Storage;
using Crux.Resilience;
using Crux.Observability;

var builder = WebApplication.CreateBuilder(args);

// Add services to the container.
var connectionString = builder.Configuration.GetConnectionString("DefaultConnection") ?? "Data Source=store.db";
builder.Services.AddDbContext<StoreDbContext>(options =>
    options.UseSqlite(connectionString));

// CORS — locked to the storefront origins so the browser accepts cross-origin requests from the
// Next.js storefront to this API. Configure via Store:AllowedOrigin or STORE_ALLOWED_ORIGIN.
// Defaults to localhost:3000 for development.
//
// Comma-separated, because a site on a custom domain has more than one origin: https://example.com
// and https://www.example.com are distinct to the browser, as is the .fly.dev hostname the apps
// keep. With a single value, a visitor who types the www. form gets a storefront that renders
// perfectly and whose every API call is blocked — visible only in the devtools console. The same
// gap opens during a domain cutover, between the storefront rebuild and the API restart.
var allowedOrigin = builder.Configuration["Store:AllowedOrigin"]
    ?? Environment.GetEnvironmentVariable("STORE_ALLOWED_ORIGIN")
    ?? "http://localhost:3000";
// Trailing slashes are trimmed: the browser's Origin header never carries one, so
// "https://example.com/" would silently match nothing.
var allowedOrigins = Array.ConvertAll(
    allowedOrigin.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries),
    o => o.TrimEnd('/'));
builder.Services.AddCors(options =>
{
    options.AddDefaultPolicy(policy =>
        policy.WithOrigins(allowedOrigins)
              .AllowAnyHeader()
              .AllowAnyMethod()
              .AllowCredentials());
});

builder.Services.AddSingleton<ITokenGenerator, TokenGenerator>();
builder.Services.AddScoped<FulfilmentService>();

// R2 -> Crux.Storage config bridge. This deployment supplies R2 credentials as R2_* env /
// R2:* config (see DEPLOYMENT.md); Crux.Storage reads the "Storage:*" section. R2StorageBridge
// maps them across (endpoint composed from the account id) so deployments keep working unchanged.
var storageOverrides = R2StorageBridge.BuildStorageOverrides(builder.Configuration);
if (storageOverrides.Count > 0)
{
    builder.Configuration.AddInMemoryCollection(storageOverrides);
}

// Content storage via Crux.Storage (R2/S3-compatible presigned URLs).
// Falls back to LocalContentStorage when a dev content directory is set.
builder.Services.AddCruxStorage(builder.Configuration);
builder.Services.AddCruxResilience();
builder.Services.AddCorrelationId();

// Correlation-id propagation on all outbound HTTP calls.
builder.Services.ConfigureHttpClientDefaults(http =>
{
    http.AddHttpMessageHandler<CorrelationIdHttpClientHandler>();
});
builder.Services.AddSingleton<IContentStorage>(sp =>
{
    var blobStore = sp.GetRequiredService<IBlobStore>();
    if (blobStore.IsConfigured)
    {
        return new CruxContentStorage(blobStore);
    }
    var cfg = sp.GetRequiredService<IConfiguration>();
    var localDir = cfg["Content:LocalDir"] ?? Environment.GetEnvironmentVariable("CONTENT_LOCAL_DIR");
    if (!string.IsNullOrWhiteSpace(localDir))
    {
        return new LocalContentStorage(localDir);
    }
    return new CruxContentStorage(blobStore); // unconfigured — IsConfigured=false, callers 503
});
builder.Services.AddHttpClient<IEmailSender, MailjetEmailSender>();

builder.Services.AddKeyedScoped<IPaymentProvider, PaddleProvider>("paddle");
builder.Services.AddKeyedScoped<IPaymentProvider, StripeProvider>("stripe");
builder.Services.AddHostedService<MoneyRailConfigGate>();

// Customer accounts: registration, login, refresh/revoke, password reset, email verification,
// social sign-in and the profile. Ported from the-introduction-exchange; the whole registration
// block lives in Auth/AuthServiceCollectionExtensions.cs.
builder.Services.AddStoreAuth(builder.Configuration);

// DataProtection key ring, persisted to the same volume as the database.
//
// Email-verification and password-reset tokens are DataProtection payloads, not database rows:
// they are only valid while the key that protected them still exists. The default key ring on a
// Linux container lands in ~/.aspnet/DataProtection-Keys inside the container filesystem, which
// is destroyed on every deploy and every machine restart. The failure that produces is quiet and
// nasty — every reset link already sitting in a customer's inbox stops working, and the endpoint
// reports it as an invalid token, which is indistinguishable from tampering.
//
// Data:KeyRingPath so the same setting works on Fly (/data, the SQLite volume — see the
// single-machine pin in DEPLOYMENT) and locally. Skipped when the directory cannot be created,
// because a developer without /data should still get a booting API.
var keyRingPath = builder.Configuration["Data:KeyRingPath"]
    ?? Environment.GetEnvironmentVariable("DATA_KEYRING_PATH");
if (!string.IsNullOrWhiteSpace(keyRingPath))
{
    Directory.CreateDirectory(keyRingPath);
    builder.Services.AddDataProtection()
        .PersistKeysToFileSystem(new DirectoryInfo(keyRingPath))
        .SetApplicationName("store-api");
}

// Forwarded headers — required for social login behind a reverse proxy (Fly, Cloudflare, nginx).
//
// The Google handler builds its redirect_uri from the CURRENT request's scheme and host. Behind
// a TLS-terminating proxy the app sees http, so it sends Google "http://api-host/signin-google"
// while the console has the https form registered, and the provider answers redirect_uri_mismatch.
// It fails only in production, only for social login, and the error surfaces on Google's page
// rather than in our logs.
//
// Locked to configured proxies: trusting X-Forwarded-* from anyone lets a caller forge its own
// client IP, and the rate limiter partitions on client IP. With no proxy configured, no
// forwarding is applied at all — which is the correct behaviour for local development.
var knownProxies = builder.Configuration["Security:KnownProxies"];
var knownNetworks = builder.Configuration["Security:KnownNetworks"];
if (!string.IsNullOrWhiteSpace(knownProxies) || !string.IsNullOrWhiteSpace(knownNetworks))
{
    builder.Services.Configure<ForwardedHeadersOptions>(options =>
    {
        options.ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto;
        options.ForwardLimit = 1;
        options.KnownProxies.Clear();
        options.KnownNetworks.Clear();

        foreach (var proxy in (knownProxies ?? string.Empty)
            .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            if (IPAddress.TryParse(proxy, out var ip))
            {
                options.KnownProxies.Add(ip);
            }
        }

        foreach (var network in (knownNetworks ?? string.Empty)
            .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            var parts = network.Split('/', 2);
            if (parts.Length == 2 && IPAddress.TryParse(parts[0], out var prefix)
                && int.TryParse(parts[1], CultureInfo.InvariantCulture, out var length))
            {
                options.KnownNetworks.Add(new Microsoft.AspNetCore.HttpOverrides.IPNetwork(prefix, length));
            }
        }
    });
}

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();

// P1-7 — rate limiting. A global per-IP fixed-window limiter caps abusive bursts (token
// guessing on /download, checkout spam). Webhooks are exempt: providers retry on non-2xx
// and a 429'd webhook would drop fulfilment. Limits are overridable via RateLimiting:*.
// The partitioning itself lives in RateLimitPolicy so the policy can be exercised by a test
// against a real limiter instead of only asserted about in a comment.
var rlPermit = builder.Configuration.GetValue<int?>("RateLimiting:PermitPerMinute")
    ?? RateLimitPolicy.DefaultPermitPerMinute;
var rlWaitlistPermit = builder.Configuration.GetValue<int?>("RateLimiting:WaitlistPermitPerMinute")
    ?? RateLimitPolicy.DefaultWaitlistPermitPerMinute;
builder.Services.AddRateLimiter(options =>
{
    options.RejectionStatusCode = StatusCodes.Status429TooManyRequests;
    options.GlobalLimiter = RateLimitPolicy.Create(rlPermit, rlWaitlistPermit);
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

// First in the pipeline, before anything reads Request.Scheme or the client IP: forwarded headers
// rewrite both, and a middleware that ran earlier would see the proxy's values. No-op unless
// Security:KnownProxies / Security:KnownNetworks is configured (see the registration above).
app.UseForwardedHeaders();

// CORS middleware — must come between routing and endpoints.
app.UseCors();

// Correlation-id must be early so every log line carries the id.
app.UseCorrelationId();

// P1-7 — rate limiter must run before endpoints so throttled requests short-circuit.
app.UseRateLimiter();

// Auth middleware. Order is load-bearing: UseAuthentication must precede UseAuthorization, or
// every [Authorize] endpoint sees an anonymous principal and 401s even with a valid token.
app.UseAuthentication();
app.UseAuthorization();

// --- PUBLIC CATALOG ENDPOINTS ---

// Rehydrate a JSON-text array column. Parse defensively: a malformed value yields an empty
// array rather than a 500, so one bad row never takes down the whole catalogue. Empty is
// also the correct representation of "not tagged" for a multi-valued facet.
static string[] RehydrateStringArray(string? json)
{
    if (string.IsNullOrWhiteSpace(json)) return [];
    try { return JsonSerializer.Deserialize<string[]>(json) ?? []; }
    catch (JsonException) { return []; }
}

// Same defensive parse for the JSON-text map columns, at file scope because BOTH catalogue
// endpoints now project the financial snapshot. Null rather than an empty map on a malformed
// value: an absent model and a model of nothing are different facts, and the storefront's
// fallback ladder branches on absence.
static Dictionary<string, string>? RehydrateMap(string? json)
{
    if (string.IsNullOrWhiteSpace(json)) return null;
    try { return JsonSerializer.Deserialize<Dictionary<string, string>>(json); }
    catch (JsonException) { return null; }
}

app.MapGet("/catalog", async (StoreDbContext db, string? market) =>
{
    // Materialise first, then shape: AdvantagesJson is JSON text (SQLite has no array
    // column) and must be rehydrated in memory — EF cannot translate the parse into SQL.
    // Hidden packs are sellable but not on the shelf: they must not appear here, in the
    // storefront grid, or in the sitemap. Their pack page still resolves for anyone holding
    // the id, which is what makes them buyable at all — see Pack.HiddenFromCatalogue.
    var packs = await db.Packs
        .Where(p => p.IsListed && !p.HiddenFromCatalogue)
        .OrderByDescending(p => p.CreatedAt)
        .ToListAsync()
        .ConfigureAwait(false);

    // ?market= is a boost-don't-block filter for the storefront's geo-aware shelf, not a second
    // sellability fence: an absent param returns every listed pack, unchanged from before this
    // existed. Many rows predate the engine tracking markets at all, so a null Market is treated
    // as "uk" here — the same rule the storefront applies when it groups packs for display.
    if (!string.IsNullOrWhiteSpace(market))
    {
        var wanted = market.Trim();
        packs = packs
            .Where(p => string.Equals(p.Market ?? "uk", wanted, StringComparison.OrdinalIgnoreCase))
            .ToList();
    }

    return packs.Select(p => new {
        p.Id,
        p.Title,
        p.OneLine,
        Price = Money.ToDisplayString(p.PricePence, "£"),
        // The same number the display string is rendered from, in pence, for the analytics
        // beacon (build plan D2). Emitted as a raw integer rather than left to the client to
        // parse back out of "£49.00": the beacon is the instrument a ladder change is judged
        // by, and an instrument that depends on reversing a display format breaks the day the
        // format does. Display still reads Price — this is not a second rendering path.
        p.PricePence,
        p.PaymentProvider,
        p.ProviderPriceId,
        // Per-pack card specifics so the catalogue sells each pack on its own merits.
        p.CardLine,
        p.Headline,
        p.WhoPays,
        p.EffortTag,
        p.ProofPoint,
        p.TimeToFirstRevenue,
        p.SourceCount,
        p.VerifiedAt,
        // Jurisdiction of the opportunity — a browse facet. Price stays GBP.
        p.Market,
        // Who the engine wrote the pack for. Projected on BOTH endpoints deliberately: a
        // field on the product page but not the shelf is a card that changes on click.
        p.Audience,
        // Discovery facets. An absent facet serialises as null and advantages as [] —
        // never as a default value, because a defaulted facet is a claim the engine never
        // made, and the buyer would filter on it believing it was real.
        p.Sector,
        p.Payer,
        p.Effort,
        p.Commitment,
        p.Mechanism,
        Advantages = RehydrateStringArray(p.AdvantagesJson),
        // The engine's modelled economics, projected on the SHELF as well as the product page
        // (2026-08-14). The card's lead figure is month-1 revenue against the pack's own price
        // (Store.Web lib/packStat.ts), and without this the shelf has no number to lead with
        // except the source count, so 62 of 62 cards would state the same class of fact.
        // Same rule as Audience above: a field on the product page but not the shelf is a card
        // that changes on click. The web degrades to the source count when it is absent, so the
        // two sides stay deployable in either order.
        FinancialSnapshot = RehydrateMap(p.FinancialSnapshotJson)
    }).ToList();
})
.WithName("GetCatalog")
.WithOpenApi();

app.MapGet("/catalog/{id}", async (string id, StoreDbContext db) =>
{
    var pack = await db.Packs.FindAsync(id).ConfigureAwait(false);
    // Unlisted is 404 here, not just absent from GET /catalog. This endpoint is the sole
    // source for the public product page (Store.Web fetchPackDetails), so serving a
    // withdrawn pack rendered its full sales page — headline, verified claims, sources and
    // a "Get instant access" button — for anyone holding the URL. POST /packs/{id}/checkout
    // already refuses an unlisted pack, so no money could move, but that made the button an
    // error rather than an absence: the buyer met a broken purchase instead of a page that
    // was honestly gone, and the withdrawn claims stayed public and indexable. For the three
    // packs quarantined on 2026-07-31 those claims are exactly what must not be readable —
    // they were verified on a provider CLAUDE.md forbids from touching the moat.
    // Deliberately not 403/410: the catalogue does not disclose which ids it once carried.
    if (pack is null || !pack.IsListed) return Results.NotFound();

    // Re-hydrate the JSON-text columns. Parse defensively: a malformed value yields null
    // rather than a 500, so one bad row never takes down a product page.
    static T? Rehydrate<T>(string? json) where T : class
    {
        if (string.IsNullOrWhiteSpace(json)) return null;
        try { return JsonSerializer.Deserialize<T>(json); }
        catch (JsonException) { return null; }
    }

    return Results.Ok(new {
        pack.Id,
        pack.Title,
        pack.OneLine,
        Price = Money.ToDisplayString(pack.PricePence, "£"),
        // See the /catalog projection: the beacon's number, not a second display path.
        pack.PricePence,
        pack.PaymentProvider,
        pack.ProviderPriceId,
        pack.DossierRef,
        // Conversion surfaces for the product page.
        pack.CardLine,
        pack.Headline,
        pack.Subhead,
        pack.ProofPoint,
        pack.WhoPays,
        pack.EffortTag,
        pack.TimeToFirstRevenue,
        pack.QaVerdictSummary,
        pack.Market,
        pack.Audience,
        pack.SourceCount,
        pack.VerifiedAt,
        // Discovery facets — same null rule as the list endpoint.
        pack.Sector,
        pack.Payer,
        pack.Effort,
        pack.Commitment,
        pack.Mechanism,
        Advantages = RehydrateStringArray(pack.AdvantagesJson),
        WhatYouGet = Rehydrate<string[]>(pack.WhatYouGetJson),
        SampleExtract = Rehydrate<string[]>(pack.SampleExtractJson),
        FinancialSnapshot = Rehydrate<Dictionary<string, string>>(pack.FinancialSnapshotJson)
    });
})
.WithName("GetPackDetails")
.WithOpenApi();

// Catalogue-wide proof: how many packs cleared every gate and are live, against how many
// were registered (the held-back ones never list). The storefront renders this as honest
// survivorship social proof. Counts only what this layer actually knows.
app.MapGet("/catalog/stats", async (StoreDbContext db) =>
{
    // Both counts exclude hidden packs. This number is shown to buyers as survivorship proof,
    // so an internal probe pack must not inflate either side of it — it cleared no gates and is
    // not on offer.
    var registered = await db.Packs.CountAsync(p => !p.HiddenFromCatalogue).ConfigureAwait(false);
    var listed = await db.Packs
        .CountAsync(p => p.IsListed && !p.HiddenFromCatalogue)
        .ConfigureAwait(false);
    return Results.Ok(new { listed, registered });
})
.WithName("GetCatalogStats")
.WithOpenApi();

// The honest end of a catalogue-wide miss: someone searched for a space we have not vetted a
// pack in, and asked to be told if one ever survives the six checks. This endpoint CAPTURES
// ONLY — it wires no marketing send, deliberately. The sub-processor list in the privacy
// notice still carries an open question about the correct Mailjet contracting entity, and
// naming the wrong one would be a false statement in a UK GDPR notice.
//
// Validation, consent hashing, and IP hashing all live in WaitlistService so they can be
// tested. This lambda is only the HTTP shell. Rate limited to 5 a minute per IP by
// RateLimitPolicy, because it is the one unauthenticated endpoint that writes personal data.
app.MapPost("/catalog/waitlist", async (
    WaitlistRequest request,
    HttpContext http,
    StoreDbContext db,
    IConfiguration config,
    CancellationToken cancellationToken) =>
{
    // No salt configured means no IP hash is stored. Hashing an IPv4 address without a secret
    // salt is not pseudonymisation — the whole space is brute-forceable in seconds — so the
    // fail-closed choice is to hold less data, not to hold a hash that pretends to protect.
    var salt = config["Store:IpHashSalt"]
        ?? Environment.GetEnvironmentVariable("STORE_IP_HASH_SALT");
    var clientIp = string.IsNullOrEmpty(salt)
        ? null
        : http.Connection.RemoteIpAddress?.ToString();

    var service = new WaitlistService(db, salt ?? string.Empty);
    var result = await service.SignUpAsync(request, clientIp, cancellationToken).ConfigureAwait(false);

    if (!result.Succeeded)
    {
        return Results.BadRequest(new { error = result.Error });
    }

    // Echo nothing back that could be used to enumerate or confirm an address, and say
    // plainly what will and will not happen next — the success copy on the storefront makes
    // the same promise, and the two must not drift.
    return Results.Accepted(value: new
    {
        status = "queued",
        message = "You're in the queue. We'll email you from support@mumchimp.com if one ships."
    });
})
.WithName("JoinCatalogWaitlist")
.WithOpenApi();

// --- INTERNAL/ENGINE ENDPOINTS ---

app.MapPost("/internal/catalog", async (PublishRequest request, HttpRequest http, StoreDbContext db, IConfiguration config, IServiceProvider sp, ILoggerFactory loggerFactory) =>
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

    // Validate facets BEFORE touching the database, so a publish carrying an unknown value
    // writes nothing at all. Junk in a facet column would surface as a filter that lies,
    // which is the one failure this whole feature exists to prevent.
    if (!PackFacets.TryValidateAll(
            request.Sector, request.Payer, request.Effort,
            request.Commitment, request.Mechanism, request.Advantages, out var facetError))
    {
        return Results.BadRequest(new { error = facetError });
    }

    var pack = await db.Packs.FindAsync(request.Id).ConfigureAwait(false);
    var isNewPack = pack == null;
    if (pack == null)
    {
        var initialPrice = request.PricePence ?? Money.DefaultPackPricePence;
        pack = new Pack
        {
            Id = request.Id,
            Title = request.Title,
            OneLine = request.OneLine,
            DossierRef = request.DossierRef,
            PricePence = initialPrice,
            // A brand new pack has no sessions in flight, so there is nothing to drain and the
            // floor is the price. Set both explicitly rather than leaning on the CLR default:
            // a stored floor of 0 reads as "any payment fulfils" to a direct reader.
            MinBillablePence = initialPrice,
            MinBillableEffectiveAt = DateTime.UtcNow,
            // No default twin here, unlike PricePence above. An absent USD price must stay
            // absent: Money.DefaultPackPricePence is a GBP number, and defaulting a USD column
            // from it would put a price on the rail that nobody declared. Null keeps the pack
            // unbillable in USD, which the fulfilment fence already enforces.
            PriceUsdCents = request.PriceUsdCents,
            MinBillableUsdCents = request.PriceUsdCents,
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
    // An EXISTING pack keeps the provider that minted its ids: since those ids are no longer
    // nulled by an omission (below), defaulting to "paddle" here would leave a live Stripe
    // pack labelled paddle while holding price_* ids — a mismatch no reader could resolve.
    pack.PaymentProvider = request.PaymentProvider
        ?? (request.PaddleProductId is not null ? "paddle" : null)
        ?? pack.PaymentProvider
        ?? "paddle";

    // Only overwrite when the publish actually CARRIED an id. Omitting them used to null them,
    // and no GET projection returns them, so a copy job routed through this endpoint could not
    // echo back what it must not disturb. A null ProviderProductId breaks FulfilmentService's
    // product lookup (p.ProviderProductId == item.ProductId): charged, never delivered.
    // Sending a different id still moves it — this guards omission, not change.
    var sentProductId = request.ProviderProductId ?? request.PaddleProductId;
    if (sentProductId is not null)
    {
        pack.ProviderProductId = sentProductId;
    }
    // The price POINTER is as money-bearing as the price NUMBER, and until 2026-08-15 only one of
    // them was defended here. PricePence is assigned on the INSERT branch above and nowhere else,
    // precisely so a republish cannot re-price a live pack behind the floor drain —
    // but the line below re-pointed checkout at whatever Price the publisher had just minted. A
    // republish could therefore move what the buyer is CHARGED without moving what the shelf SAYS,
    // and leave no trace: no PackPriceHistory row, no floor move, changeCount still 0.
    //
    // Measured live on 2026-08-15, that is exactly what had happened. `d6f72b9dc9a45c45` was
    // inserted 2026-08-01 at 4900p and republished on 2026-08-13 when the price-engine decided
    // 9999p: Stripe charged £99.99, the card read £49.00, history was empty. Eight more packs were
    // in the same state, one of them £49.00 against £79.99.
    //
    // So on UPDATE the pointer only moves when there is nothing for it to contradict — the stored
    // id is absent, or a `price_stub_*` that no checkout can bill anyway (which is what
    // tools/reprice_live_packs.py repairs through this endpoint). A publish that carries a
    // DIFFERENT real id keeps the one it already had, and says so in the log.
    //
    // Nothing legitimate loses: bridge.py's `_resolve_money_rail` deliberately reuses the pack's
    // existing Price rather than minting per publish, so an ordinary republish sends the id
    // already stored and takes the equality branch. Actually changing a price is what
    // PATCH /internal/catalog/{id}/price is for, and it moves the number, the pointer, the floor
    // and the history row in one transaction, which is the only combination that is ever correct.
    var sentPriceId = request.ProviderPriceId ?? request.PaddlePriceId;
    if (sentPriceId is not null)
    {
        var storedPriceId = pack.ProviderPriceId;
        var pointerIsUncontested = isNewPack
            || string.IsNullOrEmpty(storedPriceId)
            || storedPriceId.StartsWith("price_stub_", StringComparison.Ordinal)
            || string.Equals(storedPriceId, sentPriceId, StringComparison.Ordinal);
        if (pointerIsUncontested)
        {
            pack.ProviderPriceId = sentPriceId;
        }
        else
        {
            loggerFactory.CreateLogger("PublishPack").LogError(
                "Refusing to re-point {PackId} from price {StoredPriceId} to {SentPriceId}: this "
                + "endpoint cannot move PricePence ({PricePence}p), so moving the pointer alone "
                + "would charge a number the shelf does not show. Use the price PATCH door instead.",
                pack.Id, storedPriceId, sentPriceId, pack.PricePence);
        }
    }

    // Content metadata (set by the engine after it uploads the deliverable to R2).
    //
    // ContentVersion is owned by the SERVER, not by the publisher. No GET projection returns it,
    // so a republishing engine cannot read the current value in order to increment it: it
    // computed (missing ?? 0) + 1 and sent 1, knocking a pack on its fourth revision back to its
    // first. FulfilmentService stamps this number onto the buyer's record, so after a reset the
    // same version describes two different bundles. A CHANGED ContentHash is the signal, and the
    // increment happens here — exactly as the content PATCH already does it. A BRAND NEW pack is
    // excluded: Pack.ContentVersion already defaults to 1 (Pack.cs:87), so its first content is
    // version 1, not 2.
    var contentChanged = !isNewPack
        && request.ContentHash is not null
        && !string.Equals(request.ContentHash, pack.ContentHash, StringComparison.Ordinal);
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
        // An explicit version still wins: a restore or a migration has to be able to state one.
        pack.ContentVersion = version;
    }
    else if (contentChanged)
    {
        pack.ContentVersion += 1;
    }

    // Storefront conversion metadata (optional, additive). Only overwrite when the engine
    // sent a value, so a metadata-light republish never wipes existing copy.
    if (request.CardLine is not null) pack.CardLine = request.CardLine;
    if (request.Headline is not null) pack.Headline = request.Headline;
    if (request.Subhead is not null) pack.Subhead = request.Subhead;
    if (request.ProofPoint is not null) pack.ProofPoint = request.ProofPoint;
    if (request.WhoPays is not null) pack.WhoPays = request.WhoPays;
    if (request.EffortTag is not null) pack.EffortTag = request.EffortTag;
    if (request.TimeToFirstRevenue is not null) pack.TimeToFirstRevenue = request.TimeToFirstRevenue;
    if (request.QaVerdictSummary is not null) pack.QaVerdictSummary = request.QaVerdictSummary;
    if (request.Market is not null) pack.Market = request.Market;
    // Same only-overwrite-when-sent rule: the engine OMITS the persona rather than sending ""
    // when generation did not stamp one, so a metadata-light republish leaves a stored value
    // alone instead of blanking it.
    if (request.Audience is not null) pack.Audience = request.Audience;
    if (request.SourceCount is { } sources) pack.SourceCount = sources;
    if (request.VerifiedAt is { } verifiedAt) pack.VerifiedAt = verifiedAt;
    if (request.WhatYouGet is not null) pack.WhatYouGetJson = JsonSerializer.Serialize(request.WhatYouGet);
    if (request.SampleExtract is not null) pack.SampleExtractJson = JsonSerializer.Serialize(request.SampleExtract);
    if (request.FinancialSnapshot is not null) pack.FinancialSnapshotJson = JsonSerializer.Serialize(request.FinancialSnapshot);

    // Discovery facets. Same only-overwrite-when-sent rule as the metadata above, so a
    // facet-light republish never silently untags a pack that was tagged by the backfill.
    if (request.Sector is not null) pack.Sector = request.Sector;
    if (request.Payer is not null) pack.Payer = request.Payer;
    if (request.Effort is not null) pack.Effort = request.Effort;
    if (request.Commitment is not null) pack.Commitment = request.Commitment;
    if (request.Mechanism is not null) pack.Mechanism = request.Mechanism;
    if (request.Advantages is not null) pack.AdvantagesJson = JsonSerializer.Serialize(request.Advantages);

    // Two conditions gate going live, and both are about not taking money we cannot honour.
    //
    // List-only-after-upload: a pack may only go live once it has deliverable content. Selling
    // something we cannot deliver is the cardinal sin of this layer.
    //
    // List-only-if-billable: the price must be one THIS deployment can actually charge. The
    // publisher cannot establish that — it does not hold the key we bill through — and a price
    // id looks identical whichever account minted it. On 2026-07-31 a publisher holding a
    // sandbox key listed 10 packs whose ids were well-formed and unchargeable, so every buy
    // button returned HTTP 500 until someone noticed. Asking our own money rail is the only
    // answer that cannot drift, so the check lives here rather than in the publisher.
    var logger = loggerFactory.CreateLogger("PublishPack");
    var wantsListing = request.IsListed && !string.IsNullOrEmpty(pack.ContentKey);
    if (wantsListing)
    {
        var provider = sp.GetKeyedService<IPaymentProvider>(pack.PaymentProvider ?? "paddle");
        if (provider is null)
        {
            logger.LogError(
                "Refusing to list {PackId}: no payment provider registered for {Provider}.",
                pack.Id, pack.PaymentProvider);
            wantsListing = false;
        }
        else if (!await provider.CanBillPriceAsync(pack.ProviderPriceId ?? "", http.HttpContext?.RequestAborted ?? CancellationToken.None).ConfigureAwait(false))
        {
            logger.LogError(
                "Refusing to list {PackId}: {Provider} cannot bill price {PriceId}. Stored UNLISTED.",
                pack.Id, pack.PaymentProvider, pack.ProviderPriceId);
            wantsListing = false;
        }
    }
    pack.IsListed = wantsListing;
    pack.HiddenFromCatalogue = request.HiddenFromCatalogue;

    await db.SaveChangesAsync().ConfigureAwait(false);
    return Results.Ok(pack);
})
.WithName("PublishPack")
.WithOpenApi();

// Tag an already-published pack with discovery facets, without touching anything else about
// it. This is what the facet backfill calls: the 15 packs live today were published before the
// vocabulary existed, and re-publishing them just to add a tag would put a tagging job in a
// position to rewrite price, content hash, and listing state. It cannot reach those fields.
//
// Same fail-closed key check as POST /internal/catalog — an unauthenticated write to the
// facets would let anyone make the filter lie, which is the exact failure the facet contract
// exists to prevent.
app.MapPatch("/internal/catalog/{id}/facets", async (
    string id,
    FacetPatchRequest request,
    HttpRequest http,
    StoreDbContext db,
    IConfiguration config) =>
{
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

    // Same validator as publish, run before the lookup as well as before the write, so a
    // request carrying junk gets the same 400 whether or not the pack happens to exist.
    if (!PackFacets.TryValidateAll(
            request.Sector, request.Payer, request.Effort,
            request.Commitment, request.Mechanism, request.Advantages, out var facetError))
    {
        return Results.BadRequest(new { error = facetError });
    }

    // Market rides this endpoint but keeps its own validator: it is a shape, not a closed set
    // (PackFacets.TryValidateMarket explains why). Checked here, before the lookup, so a bad
    // code gets the same 400 as a bad facet and nothing is half-written.
    if (!PackFacets.TryValidateMarket(request.Market, out var marketError))
    {
        return Results.BadRequest(new { error = marketError });
    }

    var pack = await db.Packs.FindAsync(id).ConfigureAwait(false);
    if (pack is null) return Results.NotFound();

    // null = leave alone, "" = clear back to untagged. Without the second case a wrong tag
    // could never be withdrawn through this endpoint, and "untag it" is a legitimate
    // correction — the null rule is only trustworthy if it is reachable.
    static string? Applied(string? incoming, string? current)
    {
        if (incoming is null) return current;
        return incoming.Length == 0 ? null : incoming;
    }

    pack.Sector = Applied(request.Sector, pack.Sector);
    pack.Payer = Applied(request.Payer, pack.Payer);
    pack.Effort = Applied(request.Effort, pack.Effort);
    pack.Commitment = Applied(request.Commitment, pack.Commitment);
    pack.Mechanism = Applied(request.Mechanism, pack.Mechanism);
    pack.Market = Applied(request.Market, pack.Market);
    if (request.Advantages is not null)
    {
        pack.AdvantagesJson = request.Advantages.Length == 0
            ? null
            : JsonSerializer.Serialize(request.Advantages);
    }

    await db.SaveChangesAsync().ConfigureAwait(false);

    return Results.Ok(new
    {
        pack.Id,
        pack.Sector,
        pack.Payer,
        pack.Effort,
        pack.Commitment,
        pack.Mechanism,
        pack.Market,
        Advantages = RehydrateStringArray(pack.AdvantagesJson)
    });
})
.WithName("PatchPackFacets")
.WithOpenApi();

// Replace a live pack's storefront copy, touching nothing else about it.
//
// Same reasoning as the facets PATCH above, with a sharper edge. Routing a copy job through
// POST /internal/catalog would let it rewrite the money-bearing fields of a live listing, and
// on this endpoint that is not a hypothetical: the upsert assigns ProviderProductId and
// ProviderPriceId unconditionally on update (`request.X ?? request.PaddleX`, so omitting them
// NULLS them) while PricePence is only ever assigned on INSERT. So a copy job that re-published
// would either null the provider ids — breaking FulfilmentService's `p.ProviderProductId ==
// item.ProductId` lookup, i.e. the buyer pays and delivery never resolves — or carry freshly
// minted ones, leaving the buy button on a price minted at today's ladder number while the
// fulfilment floor still holds the old one. Both are silent in the catalogue row.
//
// ProviderProductId is returned by no GET projection, so such a job could not even read back
// what it was about to overwrite. The fix is to make the fields unreachable, not to ask the
// caller to echo them correctly.
//
// The response deliberately includes pricePence, providerPriceId and isListed alongside the
// copy. A backfill's invariance assertion should be answerable from the write's own response
// rather than a follow-up GET that could read a different pack's row after a concurrent write.
app.MapPatch("/internal/catalog/{id}/copy", async (
    string id,
    CopyPatchRequest request,
    HttpRequest http,
    StoreDbContext db,
    IConfiguration config) =>
{
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

    var pack = await db.Packs.FindAsync(id).ConfigureAwait(false);
    if (pack is null) return Results.NotFound();

    // null = leave alone, "" = clear. Same rule and same reason as the facets PATCH: "this copy
    // was wrong, take it off" has to be expressible, or null-means-no-change is a trap.
    static string? Applied(string? incoming, string? current)
    {
        if (incoming is null) return current;
        return incoming.Length == 0 ? null : incoming;
    }

    // OneLine does not follow that rule, because it is not a nullable column with a fallback
    // behind it. It is `required` on Pack and it is what the catalogue card, the pack page lead
    // paragraph, the basket line and llms.txt all print; "cleared" would render as blank space
    // directly above a buy button. So blank is refused rather than written. Withdrawing a pack
    // whose description is wrong is PATCH /internal/catalog/{id}/listing, not this.
    if (request.OneLine is not null && string.IsNullOrWhiteSpace(request.OneLine))
    {
        return Results.Problem(
            "oneLine cannot be cleared: it is required on every pack and has no fallback. "
            + "Omit the field to leave it unchanged, or withdraw the pack via PATCH /internal/catalog/{id}/listing.",
            statusCode: StatusCodes.Status400BadRequest);
    }
    if (request.OneLine is not null)
    {
        pack.OneLine = request.OneLine;
    }

    // Title is `required` on Pack and has no fallback either — a cleared one renders as a blank
    // card, a blank H1 and an empty search result — so it takes the OneLine rule, not the
    // nullable-column rule. Until 2026-08-09 this column had no narrow door at all and a copy
    // edit to it had to go through the upsert; see CopyPatchRequest for what that costs.
    if (request.Title is not null && string.IsNullOrWhiteSpace(request.Title))
    {
        return Results.Problem(
            "title cannot be cleared: it is required on every pack and has no fallback. "
            + "Omit the field to leave it unchanged, or withdraw the pack via PATCH /internal/catalog/{id}/listing.",
            statusCode: StatusCodes.Status400BadRequest);
    }
    if (request.Title is not null)
    {
        pack.Title = request.Title;
    }

    pack.CardLine = Applied(request.CardLine, pack.CardLine);
    pack.Headline = Applied(request.Headline, pack.Headline);
    pack.Subhead = Applied(request.Subhead, pack.Subhead);
    pack.ProofPoint = Applied(request.ProofPoint, pack.ProofPoint);
    pack.WhoPays = Applied(request.WhoPays, pack.WhoPays);
    pack.EffortTag = Applied(request.EffortTag, pack.EffortTag);
    pack.TimeToFirstRevenue = Applied(request.TimeToFirstRevenue, pack.TimeToFirstRevenue);
    if (request.WhatYouGet is not null)
    {
        pack.WhatYouGetJson = request.WhatYouGet.Length == 0
            ? null
            : JsonSerializer.Serialize(request.WhatYouGet);
    }
    if (request.SampleExtract is not null)
    {
        pack.SampleExtractJson = request.SampleExtract.Length == 0
            ? null
            : JsonSerializer.Serialize(request.SampleExtract);
    }

    await db.SaveChangesAsync().ConfigureAwait(false);

    return Results.Ok(new
    {
        pack.Id,
        pack.Title,
        pack.CardLine,
        pack.OneLine,
        pack.Headline,
        pack.Subhead,
        pack.ProofPoint,
        pack.WhoPays,
        pack.EffortTag,
        pack.TimeToFirstRevenue,
        WhatYouGet = RehydrateStringArray(pack.WhatYouGetJson),
        SampleExtract = RehydrateStringArray(pack.SampleExtractJson),
        // Invariants, echoed so the caller can assert on them without a second read.
        pack.PricePence,
        pack.MinBillablePence,
        pack.ProviderPriceId,
        pack.ProviderProductId,
        pack.IsListed,
        pack.ContentKey,
    });
})
.WithName("PatchPackCopy")
.WithOpenApi();

// Withdraw a pack from sale (or restore one), touching nothing else about it.
//
// The alternative was re-POSTing the pack to /internal/catalog with IsListed=false, but that
// endpoint is an upsert: it assigns ProviderProductId, ProviderPriceId and DossierRef from the
// request unconditionally, and those are not readable back from the public /catalog. Pulling a
// pack that way silently nulls its Stripe ids — a moderation action destroying the money rail.
// Hence a door that can only reach the listing bit.
//
// Restoring is deliberately subject to the same rule as publishing: a pack with no ContentKey
// cannot go live, because selling what we cannot deliver is the cardinal sin of this layer.
app.MapPatch("/internal/catalog/{id}/listing", async (
    string id,
    ListingPatchRequest request,
    HttpRequest http,
    StoreDbContext db,
    IConfiguration config) =>
{
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

    if (string.IsNullOrWhiteSpace(request.Reason))
    {
        return Results.BadRequest(new { error = "reason is required — an unexplained delisting reads as a bug" });
    }

    var pack = await db.Packs.FindAsync(id).ConfigureAwait(false);
    if (pack is null) return Results.NotFound();

    if (request.IsListed && string.IsNullOrEmpty(pack.ContentKey))
    {
        return Results.BadRequest(new { error = "cannot list a pack with no deliverable content" });
    }

    pack.IsListed = request.IsListed;
    pack.DelistReason = request.Reason;
    pack.DelistedAt = request.IsListed ? null : DateTime.UtcNow;

    await db.SaveChangesAsync().ConfigureAwait(false);

    return Results.Ok(new { pack.Id, pack.IsListed, pack.DelistReason, pack.DelistedAt });
})
.WithName("PatchPackListing")
.WithOpenApi();

// Repoint a pack's deliverable at a new content object, touching nothing else about it.
//
// Content keys are content-addressed (packs/<id>/<sha256>.zip), so ANY bundle change mints a
// new object key and the listing must be repointed to it — but a bundle-format backfill must
// never hold the power to rewrite price, provider ids or listing state, and /internal/catalog
// assigns those unconditionally. Same narrow-door rationale as the facet and listing patches.
//
// The key must parse as this pack's own content-addressed path with the hash it claims:
// accepting an arbitrary key would let a bad call point pack A's download at pack B's zip.
app.MapPatch("/internal/catalog/{id}/content", async (
    string id,
    ContentPatchRequest request,
    HttpRequest http,
    StoreDbContext db,
    IConfiguration config) =>
{
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

    if (string.IsNullOrWhiteSpace(request.Reason))
    {
        return Results.BadRequest(new { error = "reason is required — an unexplained content repoint reads as a bug" });
    }
    if (string.IsNullOrWhiteSpace(request.ContentKey) || string.IsNullOrWhiteSpace(request.ContentHash))
    {
        return Results.BadRequest(new { error = "contentKey and contentHash are both required" });
    }
    if (!string.Equals(request.ContentKey, $"packs/{id}/{request.ContentHash}.zip", StringComparison.Ordinal))
    {
        return Results.BadRequest(new { error = $"contentKey must be packs/{id}/<contentHash>.zip for this pack" });
    }

    var pack = await db.Packs.FindAsync(id).ConfigureAwait(false);
    if (pack is null) return Results.NotFound();

    // Only a pack that already has a deliverable can be repointed: this door updates content,
    // it does not grant it. First-time content still goes through /internal/catalog, where
    // list-only-after-upload and billability are enforced together.
    if (string.IsNullOrEmpty(pack.ContentKey))
    {
        return Results.BadRequest(new { error = "pack has no content to repoint — publish it through /internal/catalog first" });
    }

    pack.ContentKey = request.ContentKey;
    pack.ContentHash = request.ContentHash;
    pack.ContentVersion += 1;

    await db.SaveChangesAsync().ConfigureAwait(false);

    return Results.Ok(new { pack.Id, pack.ContentKey, pack.ContentHash, pack.ContentVersion });
})
.WithName("PatchPackContent")
.WithOpenApi();

// How long the old fulfilment floor is held after a price RISE. Stripe Checkout Sessions expire
// 24h after creation, so 24h is the real bound; the extra two hours cover clock skew between us
// and the provider and a session created in the same second as the change. Erring long costs
// nothing — during the drain the fence still refuses genuine underpayment, it is simply
// calibrated to the old price — whereas erring short charges a real buyer and refuses delivery.
var CheckoutSessionDrain = TimeSpan.FromHours(26);

// Move a pack's price, and the fulfilment floor with it, in one transaction.
//
// This is the ONLY writer of price. Before it existed a published pack's price could not be
// changed at all: /internal/catalog assigns PricePence on INSERT and silently omits it on the
// update path, so a re-POST left the old price in place while appearing to succeed.
//
// The hard part is not the write, it is the drain. Fulfilment gates delivery on the pack row
// while Stripe Checkout Sessions live up to 24h, so at any moment a price moves there are live
// sessions minted at the old price. A single column breaks in both directions — a cut strands
// buyers paying the new lower price against the old higher number, a rise strands buyers paying
// the old lower price against the new higher one — and the two need opposite write orderings,
// so no ordering fixes both. Pack.MinBillablePence + MinBillableEffectiveAt remove the race
// instead: see Pack.EffectiveFloorPence.
//
//   cut  (new <= floor): the new price is already the minimum, so every live session clears it.
//                        No drain. The floor becomes the new price immediately.
//   rise (new >  floor): hold the OLD floor until the longest-lived session has expired, then
//                        the floor rejoins PricePence on its own. Expressed as a timestamp, not
//                        a scheduled job, so there is no tick to miss and a process that was
//                        down for the whole window still computes the right answer.
//
// Taking min() against the CURRENT effective floor rather than against PricePence is what makes
// repeated changes inside one drain window safe: a second rise extends the window rather than
// lifting the floor over sessions still in flight.
app.MapPatch("/internal/catalog/{id}/price", async (
    string id,
    PricePatchRequest request,
    HttpRequest http,
    StoreDbContext db,
    IConfiguration config,
    IServiceProvider sp,
    ILoggerFactory loggerFactory) =>
{
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

    if (string.IsNullOrWhiteSpace(request.Reason))
    {
        return Results.BadRequest(new { error = "reason is required — an unexplained price move reads as a bug" });
    }
    if (string.IsNullOrWhiteSpace(request.Actor))
    {
        return Results.BadRequest(new { error = "actor is required — a price move must be attributable" });
    }
    if (request.PricePence <= 0)
    {
        return Results.BadRequest(new { error = "pricePence must be positive" });
    }
    // A stub id is what bridge.py mints when it cannot reach a real payment rail, and checkout
    // builds a Stripe session from whatever is stored — so a stub here would render a buy button
    // that 500s. bridge.py refuses to LIST one; refuse to STORE one, on both ends of the wire.
    if (request.ProviderPriceId is not null && request.ProviderPriceId.StartsWith("price_stub_", StringComparison.Ordinal))
    {
        return Results.BadRequest(new { error = "refusing a stub price id — it cannot take money" });
    }

    var pack = await db.Packs.FindAsync(id).ConfigureAwait(false);
    if (pack is null) return Results.NotFound();

    var logger = loggerFactory.CreateLogger("PatchPackPrice");
    var ct = http.HttpContext?.RequestAborted ?? CancellationToken.None;

    // Verify billability BEFORE committing anything. The publish path already refuses to list a
    // price the provider cannot bill; a re-price must clear the same bar, or this endpoint would
    // be a way to walk a listed pack into an unbillable state that publish would have rejected.
    // Only when the pack is actually sellable: an unlisted pack has no session to protect and
    // may legitimately be re-priced while its rail is unconfigured.
    if (pack.IsListed)
    {
        if (string.IsNullOrEmpty(request.ProviderPriceId))
        {
            return Results.BadRequest(new { error = "a listed pack needs a billable providerPriceId to re-price" });
        }
        var provider = sp.GetKeyedService<IPaymentProvider>(pack.PaymentProvider ?? "paddle");
        if (provider is null)
        {
            logger.LogError("Refusing to re-price {PackId}: no payment provider registered for {Provider}.",
                pack.Id, pack.PaymentProvider);
            return Results.BadRequest(new { error = "no payment provider registered for this pack" });
        }
        if (!await provider.CanBillPriceAsync(request.ProviderPriceId, ct).ConfigureAwait(false))
        {
            logger.LogError("Refusing to re-price {PackId}: {Provider} cannot bill price {PriceId}.",
                pack.Id, pack.PaymentProvider, request.ProviderPriceId);
            return Results.BadRequest(new { error = "provider cannot bill that price id" });
        }
    }

    var now = DateTime.UtcNow;
    var previousPrice = pack.PricePence;
    var currentFloor = pack.EffectiveFloorPence(now);

    // Never lift the floor above a price a live session could carry.
    pack.MinBillablePence = Math.Min(currentFloor, request.PricePence);
    pack.MinBillableEffectiveAt = request.PricePence > currentFloor
        ? now + CheckoutSessionDrain
        : now;
    pack.PricePence = request.PricePence;
    if (!string.IsNullOrEmpty(request.ProviderPriceId))
    {
        pack.ProviderPriceId = request.ProviderPriceId;
    }

    // The USD rung moves under exactly the same drain rule, for exactly the same reason: a live
    // USD Checkout Session minted at the old rung is still payable for up to 24h, and gating it
    // on the new one refuses money already taken.
    //
    // Omission leaves the USD price untouched rather than clearing it. Clearing on omission would
    // make every existing GBP-only re-pricing caller silently strip USD billability off a pack the
    // moment this field shipped — the same omission-nulls-it defect the ProviderProductId comment
    // above records, on a column that decides whether a US buyer can be served at all.
    if (request.PriceUsdCents is { } usd)
    {
        if (usd <= 0)
        {
            return Results.BadRequest(new { error = "priceUsdCents must be positive when present" });
        }
        var currentUsdFloor = pack.EffectiveFloorMinorUnits("USD", now) ?? usd;
        pack.MinBillableUsdCents = Math.Min(currentUsdFloor, usd);
        // One drain clock covers both ladders. They are moved together by one decision
        // (PriceDecision mints both), so a second timestamp could only ever disagree with this
        // one — and a disagreement here is a paying buyer refused.
        if (usd > currentUsdFloor && pack.MinBillableEffectiveAt <= now)
        {
            pack.MinBillableEffectiveAt = now + CheckoutSessionDrain;
        }
        pack.PriceUsdCents = usd;
    }

    // Same transaction as the change, deliberately: a history row written afterwards is a row
    // that can be missing, and a sale whose price window cannot be reconstructed is unattributable
    // forever after.
    db.PackPriceHistory.Add(new PackPriceHistory
    {
        PackId = pack.Id,
        FromPence = previousPrice,
        ToPence = request.PricePence,
        MinBillablePence = pack.MinBillablePence,
        ProviderPriceId = pack.ProviderPriceId,
        Reason = request.Reason,
        Actor = request.Actor,
        RationaleRef = request.RationaleRef,
        CreatedAt = now,
    });

    await db.SaveChangesAsync().ConfigureAwait(false);

    logger.LogInformation(
        "Re-priced {PackId} {From}p -> {To}p (floor {Floor}p until {Until:o}) by {Actor}: {Reason}",
        pack.Id, previousPrice, pack.PricePence, pack.MinBillablePence, pack.MinBillableEffectiveAt,
        request.Actor, request.Reason);

    return Results.Ok(new
    {
        pack.Id,
        pack.PricePence,
        pack.MinBillablePence,
        pack.MinBillableEffectiveAt,
        pack.ProviderPriceId,
    });
})
.WithName("PatchPackPrice")
.WithOpenApi();

// Read a pack's current content pointer. The backfill needs to know WHICH stored object a
// listing serves before rebuilding it: content-addressing keeps every superseded upload, so
// a pack republished twice has three objects under packs/<id>/ and only the database knows
// which one buyers receive. Newest-by-LastModified is a heuristic that goes wrong exactly
// when a past upload succeeded but its catalog update failed. Internal (key-gated) because
// content keys are presign targets, not public catalogue data.
app.MapGet("/internal/catalog/{id}/content", async (
    string id,
    HttpRequest http,
    StoreDbContext db,
    IConfiguration config) =>
{
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

    var pack = await db.Packs.FindAsync(id).ConfigureAwait(false);
    if (pack is null) return Results.NotFound();

    return Results.Ok(new { pack.Id, pack.ContentKey, pack.ContentHash, pack.ContentVersion });
})
.WithName("GetPackContent")
.WithOpenApi();

// Read a pack's price history — the rows PatchPackPrice writes, plus the two things a caller
// cannot derive from those rows alone.
//
// The table has been written since the AddPackPriceFloorAndHistory migration and, until this
// endpoint, was read by nothing: a derivation record nobody can retrieve is a record in name
// only. PackPriceHistory exists so a sale can be attributed to the price the buyer was actually
// shown (see the entity's own summary), and that is a point-in-time question. Answering it from
// a raw row list means getting two boundary cases right, so this endpoint answers it once:
//
//   origin — publish assigns PricePence on INSERT (the /internal/catalog upsert above) and
//            writes NO history row. The price before the first change therefore survives only as
//            that first row's FromPence, and a pack never re-priced has an empty history whose
//            correct answer for every timestamp is still a price. A caller reading rows alone
//            sees nothing and concludes nothing was charged.
//   gaps   — the record is worth reading only if it is CONTINUOUS. PricePence is assigned in
//            exactly two places today, the publish INSERT and PatchPackPrice, which writes its
//            row inside the same transaction as the change — so the chain cannot currently
//            break. `continuous` is not a restatement of that fact: it is what still holds if a
//            third writer is added later, and it fails loudly rather than serving a
//            plausible-looking history that silently omits a change.
//
// Internal (key-gated) like the rest of /internal/catalog, and for a sharper reason than the
// others: reason/actor are operational notes, and a public price-change log hands a competitor
// every pricing experiment we have run, including the ones we abandoned.
app.MapGet("/internal/catalog/{id}/price-history", async (
    string id,
    HttpRequest http,
    StoreDbContext db,
    IConfiguration config,
    DateTimeOffset? asOf,
    int? limit) =>
{
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

    var pack = await db.Packs.FindAsync(id).ConfigureAwait(false);
    if (pack is null) return Results.NotFound();

    // Oldest-first: continuity and the as-of scan are both chronological. Id breaks ties so the
    // order is total — two changes landing inside one clock tick would otherwise order
    // arbitrarily, and "arbitrarily" includes differently on two reads of the same data.
    var rows = await db.PackPriceHistory
        .Where(h => h.PackId == id)
        .OrderBy(h => h.CreatedAt).ThenBy(h => h.Id)
        .ToListAsync().ConfigureAwait(false);

    var originPence = rows.Count > 0 ? rows[0].FromPence : pack.PricePence;

    var continuous = rows.Count == 0 || rows[^1].ToPence == pack.PricePence;
    for (var i = 1; i < rows.Count && continuous; i++)
    {
        continuous = rows[i].FromPence == rows[i - 1].ToPence;
    }

    object? at = null;
    if (asOf is not null)
    {
        var when = asOf.Value.UtcDateTime;
        if (when < pack.CreatedAt)
        {
            // Distinct from "origin": the pack did not exist, so there was no price to be shown.
            // Returning the origin price here would invent a listing that was never on sale.
            at = new
            {
                asOf = when,
                pricePence = (long?)null,
                minBillablePence = (long?)null,
                providerPriceId = (string?)null,
                source = "before-publish",
                changeId = (long?)null,
            };
        }
        else
        {
            // The last change applied at or before `when`. A change is live from its own
            // CreatedAt, so the boundary is inclusive: a sale stamped at the same instant as a
            // re-price was billed the new price.
            PackPriceHistory? applied = null;
            foreach (var h in rows)
            {
                if (h.CreatedAt > when) break;
                applied = h;
            }
            at = applied is null
                // Before the first change. The floor and provider price of that era were never
                // recorded — null says so rather than lending today's values a false history.
                ? new
                {
                    asOf = when,
                    pricePence = (long?)originPence,
                    minBillablePence = (long?)null,
                    providerPriceId = (string?)null,
                    source = "origin",
                    changeId = (long?)null,
                }
                : new
                {
                    asOf = when,
                    pricePence = (long?)applied.ToPence,
                    minBillablePence = (long?)applied.MinBillablePence,
                    providerPriceId = applied.ProviderPriceId,
                    source = "history",
                    changeId = (long?)applied.Id,
                };
        }
    }

    // The limit bounds the RESPONSE, not the scan. Continuity and as-of are properties of the
    // whole chain, so truncating before computing them would make a complete history read as a
    // broken one — the exact false alarm this endpoint exists to prevent. Newest-first on the
    // way out, which is the order a human reads a change log in.
    var take = Math.Clamp(limit ?? 200, 1, 1000);
    var page = rows.AsEnumerable().Reverse().Take(take).Select(h => new
    {
        id = h.Id,
        fromPence = h.FromPence,
        toPence = h.ToPence,
        minBillablePence = h.MinBillablePence,
        providerPriceId = h.ProviderPriceId,
        reason = h.Reason,
        actor = h.Actor,
        rationaleRef = h.RationaleRef,
        createdAt = h.CreatedAt,
    }).ToList();

    return Results.Ok(new
    {
        packId = pack.Id,
        currentPricePence = pack.PricePence,
        currentMinBillablePence = pack.MinBillablePence,
        publishedAt = pack.CreatedAt,
        originPricePence = originPence,
        changeCount = rows.Count,
        continuous,
        truncated = rows.Count > page.Count,
        asOf = at,
        history = page,
    });
})
.WithName("GetPackPriceHistory")
.WithOpenApi();

// Engine publish-authorization gate. The engine calls this BEFORE bundling/provisioning a
// pack to confirm it is entitled to publish. A separate key from the internal-catalog key so
// the two authorities can be rotated independently. Fail closed: 503 when no key is
// configured, 401 on mismatch. (MoneyRailConfigGate rejects the dev placeholder outside
// Development, so a real secret is required in production.)
app.MapPost("/entitlements", (HttpRequest http, IConfiguration config) =>
{
    var expectedKey = config["Store:EntitlementsApiKey"]
        ?? Environment.GetEnvironmentVariable("PROSPECTOR_ENTITLEMENTS_API_KEY");
    if (string.IsNullOrEmpty(expectedKey))
    {
        return Results.Problem("Entitlements API key not configured", statusCode: StatusCodes.Status503ServiceUnavailable);
    }

    var auth = http.Headers.Authorization.ToString();
    const string prefix = "Bearer ";
    var providedKey = auth.StartsWith(prefix, StringComparison.Ordinal) ? auth[prefix.Length..] : string.Empty;
    if (string.IsNullOrEmpty(providedKey) ||
        !CryptographicOperations.FixedTimeEquals(
            Encoding.UTF8.GetBytes(providedKey),
            Encoding.UTF8.GetBytes(expectedKey)))
    {
        return Results.Unauthorized();
    }

    return Results.Ok(new { ok = true });
})
.WithName("CheckEntitlement")
.WithOpenApi();

// --- WEBHOOK + DELIVERY ENDPOINTS ---

// Dev-only deliverable streaming for LocalContentStorage. Mapped ONLY in Development because
// the URLs LocalContentStorage mints are unsigned. In production, R2 presigned URLs serve
// content and this endpoint does not exist.
if (app.Environment.IsDevelopment())
{
    app.MapGet("/dev-content/{**key}", (string key, IContentStorage storage) =>
    {
        if (storage is not LocalContentStorage local || !local.IsConfigured)
        {
            return Results.NotFound();
        }
        var path = local.ResolvePath(key);
        if (path is null || !File.Exists(path))
        {
            return Results.NotFound();
        }
        return Results.File(File.OpenRead(path), "application/zip", Path.GetFileName(path));
    });
}

// Checkout (single pack and basket) — see Endpoints/CheckoutEndpoints.cs.
app.MapCheckoutEndpoints();

app.MapWebhookEndpoints();
app.MapDeliveryEndpoints();

// First-party storefront analytics (ingest + key-gated summary) — see Endpoints/AnalyticsEndpoints.cs.
app.MapAnalyticsEndpoints();

// Accounts: /v1/auth/* (register, login, refresh, logout, password reset, verify-email) and
// /v1/auth/external/* (social sign-in, link/unlink) — see Auth/.
app.MapAuthEndpoints();
app.MapExternalAuthEndpoints();
app.MapAccountOrdersEndpoints();

// Founder preview: read any pack without buying it, fenced on an allowlist of authenticated,
// provider-verified addresses — see Endpoints/FounderPreviewEndpoints.cs.
app.MapFounderPreviewEndpoints();

await app.RunAsync().ConfigureAwait(false);

// Top-level statements compile to an internal Program, which WebApplicationFactory<T> cannot
// name. Declaring it public here is the whole handshake that lets the tests boot this exact
// app — same DI, same middleware, same endpoint wiring — rather than a re-declared stand-in
// that could drift from it.
public partial class Program
{
    // Never instantiated — the class exists only so WebApplicationFactory<Program> can name it.
    // Protected rather than suppressing S1118: the analyzer's point (nobody should construct a
    // holder of static members) is correct, and this satisfies it honestly.
    protected Program() { }
}
