using System.Text.Json;
using FluentValidation;
using MediatR;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Identity;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.IdentityModel.Tokens;
using Store.Api.Common;
using Store.Api.Common.Audit;
using Store.Api.Identity;
using Store.Api.Persistence;
using Store.Api.Services;
using Store.Catalog.Domain.Identity;
using Store.Catalog.Persistence;

namespace Store.Api.Auth;

/// <summary>
/// Everything the auth slices need, in one call. This replaces the introduction-exchange's
/// IdentityDependencyInjection, which could not be copied: ~90% of it registered marketplace
/// services (escrow, disputes, connector payouts) and it seeded a Buyer/Connector role set the
/// store does not have.
/// </summary>
public static class AuthServiceCollectionExtensions
{
    public static IServiceCollection AddStoreAuth(this IServiceCollection services, IConfiguration configuration)
    {
        ArgumentNullException.ThrowIfNull(services);
        ArgumentNullException.ThrowIfNull(configuration);

        services.AddOptions<JwtOptions>()
            .Bind(configuration.GetSection(JwtOptions.SectionName))
            .ValidateDataAnnotations()
            .ValidateOnStart();
        services.Configure<EmailOptions>(configuration.GetSection(EmailOptions.SectionName));

        AddIdentityCore(services);
        AddAuthPipeline(services, configuration);
        AddAuthServices(services);
        return services;
    }

    private static void AddIdentityCore(IServiceCollection services)
    {
        services.AddIdentity<StoreUser, IdentityRole<Guid>>(options =>
        {
            // Matches the RegisterCommandValidator minimum (8). Length is the requirement that
            // actually costs an attacker work; the character-class rules are off because they push
            // people to "Password1!" and Identity already hashes with PBKDF2.
            options.Password.RequiredLength = 8;
            options.Password.RequireDigit = false;
            options.Password.RequireUppercase = false;
            options.Password.RequireLowercase = false;
            options.Password.RequireNonAlphanumeric = false;

            // LoginCommand quotes AuthConstants.LockoutDurationMinutes back to the user; this is the
            // value actually enforced. They must stay equal — see the remark on that constant.
            options.Lockout.DefaultLockoutTimeSpan = TimeSpan.FromMinutes(AuthConstants.LockoutDurationMinutes);
            options.Lockout.MaxFailedAccessAttempts = 5;
            options.Lockout.AllowedForNewUsers = true;

            // The store joins an order to an account by email string (D1), so a second account
            // holding the same address would be shown someone else's purchases. Identity enforces
            // this in the user manager; StoreDbContext also carries a UNIQUE index on
            // NormalizedEmail so a race that slips past the manager still fails at the database.
            options.User.RequireUniqueEmail = true;

            // Registration issues no JWT until the address is confirmed, and LoginCommand refuses
            // an unconfirmed account. Without this, a signup could read order history for an
            // address they merely typed.
            options.SignIn.RequireConfirmedEmail = true;
        })
        .AddEntityFrameworkStores<StoreDbContext>()
        .AddDefaultTokenProviders();
    }

    private static void AddAuthPipeline(IServiceCollection services, IConfiguration configuration)
    {
        var jwt = configuration.GetSection(JwtOptions.SectionName).Get<JwtOptions>() ?? new JwtOptions();

        // Fail fast for the same reason SigningKeyPem does, one line down. Issuer and Audience
        // default to "" (JwtOptions.cs:10-11), and the validator below runs with
        // ValidateIssuer/ValidateAudience = true — so an instance started without them boots
        // cleanly, logs in successfully, mints tokens carrying no `aud`, and then answers EVERY
        // authenticated request with a bare 401 whose only explanation is a WWW-Authenticate
        // header ("The audience 'empty' is invalid"). Observed on this machine, 2026-08-01, before
        // this check existed. A deploy that forgets one Fly secret must not look healthy.
        if (string.IsNullOrWhiteSpace(jwt.Issuer) || string.IsNullOrWhiteSpace(jwt.Audience))
        {
            throw new InvalidOperationException(
                "Jwt:Issuer and Jwt:Audience must both be configured (Jwt__Issuer / Jwt__Audience). "
                + "Tokens are validated against them, so leaving either empty makes every "
                + "authenticated request fail with 401 while the app appears healthy.");
        }

        // Built once, here, and registered as the singleton the rest of the app resolves. Both
        // things that must agree about the key — JwtTokenService signing and JwtBearer validating —
        // therefore hold the SAME RsaSecurityKey object. Resolving it through a throwaway
        // BuildServiceProvider() inside the options callback would instead construct a second
        // provider in a second container: it would work, because both parse the same PEM, and it
        // would keep working right up until the day the key is rotated at runtime.
        var signingKeyProvider = new ConfigJwtSigningKeyProvider(jwt.SigningKeyPem, jwt.KeyId);
        services.AddSingleton<IJwtSigningKeyProvider>(signingKeyProvider);

        // AddIdentity set the default scheme to Identity's application cookie. This API is a bearer
        // API: without the override, an unauthenticated request would be answered with a 302 to a
        // login page that does not exist here, instead of a 401 the frontend can act on.
        var auth = services.AddAuthentication(options =>
        {
            options.DefaultAuthenticateScheme = JwtBearerDefaults.AuthenticationScheme;
            options.DefaultChallengeScheme = JwtBearerDefaults.AuthenticationScheme;
        });

        auth.AddJwtBearer(options =>
        {
            options.TokenValidationParameters = new TokenValidationParameters
            {
                ValidateIssuer = true,
                ValidateAudience = true,
                ValidateLifetime = true,
                ValidateIssuerSigningKey = true,
                ValidIssuer = jwt.Issuer,
                ValidAudience = jwt.Audience,
                IssuerSigningKey = signingKeyProvider.SigningKey,
                ClockSkew = TimeSpan.FromSeconds(AuthConstants.ClockSkewToleranceSeconds),
            };

            options.Events = new JwtBearerEvents
            {
                // Accept the session from the httpOnly "jwt" cookie when no Authorization header is
                // present. LoginCommand.cs:104, RefreshTokenCommand.cs:86 and
                // ExternalAuthEndpoints.cs:79 all already SET that cookie; until this hook existed
                // nothing ever READ it, so it was decorative and the browser had to hold the token
                // in JavaScript instead.
                //
                // Reading it here is what lets the storefront keep NO token in JS at all: any XSS
                // that lands on the page still cannot exfiltrate a session, because the credential
                // is HttpOnly. The cookie is SameSite=Strict (JwtTokenService.cs:132) and the
                // storefront reaches this API through its own origin via the Next.js rewrite
                // (next.config.ts:78-79), so the browser treats every call as same-site and sends
                // it — while a genuine cross-site request from an attacker's page carries no cookie
                // at all, which is the CSRF defence.
                //
                // Header first, cookie second, never both: a caller that sends an explicit bearer
                // token (curl, the test suite, a future mobile client) must not have it silently
                // overridden by whatever cookie the browser happened to attach.
                OnMessageReceived = context =>
                {
                    if (string.IsNullOrEmpty(context.Token)
                        && context.Request.Cookies.TryGetValue("jwt", out var cookieToken)
                        && !string.IsNullOrEmpty(cookieToken))
                    {
                        context.Token = cookieToken;
                    }

                    return Task.CompletedTask;
                },

                // Signature-valid is not the same as still-valid. Logout adds the token's JTI to a
                // deny list; without this check a stolen token keeps working until it expires,
                // which the 720-minute interim expiry would make a 12-hour window.
                OnTokenValidated = async context =>
                {
                    var jti = context.Principal?.FindFirst("jti")?.Value;
                    if (string.IsNullOrEmpty(jti))
                        return;

                    var revocation = context.HttpContext.RequestServices.GetRequiredService<ITokenRevocationService>();
                    if (await revocation.IsTokenRevokedAsync(jti, context.HttpContext.RequestAborted).ConfigureAwait(false))
                        context.Fail("Token has been revoked.");
                },
            };
        });

        // The external provider needs somewhere to park the identity between the provider redirect
        // and our callback. AddIdentity already registered that cookie under
        // IdentityConstants.ExternalScheme, so this CONFIGURES it rather than adding it — calling
        // auth.AddCookie(IdentityConstants.ExternalScheme, ...) here throws at startup with
        // "Scheme already exists: Identity.External". It is a short-lived correlation cookie, not a
        // session: the callback reads it once and deletes it, then issues a JWT like any other login.
        services.Configure<CookieAuthenticationOptions>(IdentityConstants.ExternalScheme, options =>
        {
            options.Cookie.HttpOnly = true;
            options.Cookie.SameSite = SameSiteMode.Lax;   // Lax, not Strict: the provider redirects back cross-site.
            options.Cookie.SecurePolicy = CookieSecurePolicy.Always;
            options.ExpireTimeSpan = TimeSpan.FromMinutes(10);
        });

        AddSocialProviders(auth, configuration);
        services.AddAuthorization();
    }

    /// <summary>
    /// Registers a social provider only when its credentials are present. A provider with no client
    /// id would otherwise register a scheme, appear in the sign-in options the frontend reads, and
    /// fail at the provider with an opaque error after the user had already clicked. Absent
    /// credentials mean the button is simply not offered, and /challenge/{provider} answers 400.
    /// </summary>
    private static void AddSocialProviders(AuthenticationBuilder auth, IConfiguration configuration)
    {
        var googleId = configuration["Authentication:Google:ClientId"];
        var googleSecret = configuration["Authentication:Google:ClientSecret"];
        if (!string.IsNullOrWhiteSpace(googleId) && !string.IsNullOrWhiteSpace(googleSecret))
        {
            auth.AddGoogle("Google", options =>
            {
                options.ClientId = googleId;
                options.ClientSecret = googleSecret;
                options.SignInScheme = IdentityConstants.ExternalScheme;

                // email_verified is the anti-hijack gate (D2). ExternalLoginCallbackCommand
                // consolidates a social login onto an existing password account when the addresses
                // match — so an unverified provider email would let anyone who can type a victim's
                // address at a sloppy provider walk into that account. The claim must be present
                // and true or the callback refuses. Google does not send it by default; asking for
                // it here is what makes the check meaningful rather than vacuous.
                options.ClaimActions.MapJsonKey("email_verified", "email_verified", "boolean");
                options.Scope.Add("openid");
                options.Scope.Add("email");
                options.Scope.Add("profile");
                options.SaveTokens = false;   // Nothing calls Google's API on the user's behalf.
            });
        }
    }

    private static void AddAuthServices(IServiceCollection services)
    {
        // IJwtSigningKeyProvider is registered in AddAuthPipeline — it must exist before JwtBearer
        // is configured, and both must share the one instance.
        services.AddScoped<IJwtTokenService, JwtTokenService>();
        // RefreshTokenService implements two interfaces: IRefreshTokenService (issue/rotate/revoke)
        // and IRefreshTokenReader (the read-only lookup RefreshTokenCommandHandler takes). Both
        // forward to one scoped instance rather than being registered separately, so a rotation and
        // the read that follows it in the same request see the same tracked entities.
        services.AddScoped<RefreshTokenService>();
        services.AddScoped<IRefreshTokenService>(sp => sp.GetRequiredService<RefreshTokenService>());
        services.AddScoped<IRefreshTokenReader>(sp => sp.GetRequiredService<RefreshTokenService>());
        services.AddScoped<ITokenRevocationService, TokenRevocationService>();
        services.AddScoped<IResilientTransaction, ResilientTransaction>();
        services.AddScoped<IAuditLogger, LoggingAuditLogger>();
        services.AddSingleton<ICriticalEmailAlerter, LoggingCriticalEmailAlerter>();
        services.AddSingleton<IExternalAuthCodeStore, ExternalAuthCodeStore>();
        services.AddMemoryCache();

        // The auth emails go out through the SAME Mailjet sender as fulfilment mail, so there is
        // one set of credentials and one sending domain to authenticate. AddHttpClient registers
        // the concrete type against IEmailSender only, hence the forward.
        services.TryAddScoped<ITransactionalEmailSender>(sp =>
            (ITransactionalEmailSender)sp.GetRequiredService<IEmailSender>());

        services.AddMediatR(cfg => cfg.RegisterServicesFromAssemblyContaining<RegisterCommand>());
        services.AddValidatorsFromAssemblyContaining<RegisterCommandValidator>();
        services.AddTransient(typeof(IPipelineBehavior<,>), typeof(ValidationBehavior<,>));
    }
}
