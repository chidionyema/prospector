using System.Security.Claims;
using System.Text.Json.Serialization;
using MediatR;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Identity;
using Microsoft.Extensions.Options;
using Store.Api.Common;
using Store.Api.Identity;
using Store.Catalog.Domain.Identity;

namespace Store.Api.Auth;

/// <summary>
/// Social login HTTP surface. The browser-facing OAuth redirect uses a one-time code (D1): the
/// provider lands on the API, the API mints tokens and 302s to the web with only an opaque code,
/// and the web exchanges that code for the tokens in a response body — so a JWT never appears in a
/// URL, browser history, or an access log. Linking an extra provider from Settings uses the
/// link-ticket pattern (D9).
///
/// Which providers exist is not decided here. <see cref="ResolveSchemeAsync"/> asks the
/// authentication system what is registered, so <c>/challenge/{provider}</c> answers 400
/// "Unknown or unconfigured provider" for anything not wired in
/// <c>AuthServiceCollectionExtensions.AddStoreAuth</c> — adding a provider is a DI change, not an
/// endpoint change.
/// </summary>
public static class ExternalAuthEndpoints
{
    public sealed class ExchangeRequest
    {
        [JsonPropertyName("code")] public string Code { get; set; } = string.Empty;
    }

    public static void MapExternalAuthEndpoints(this IEndpointRouteBuilder app)
    {
        var ext = app.MapGroup("/v1/auth/external");

        // ── 1. Begin sign-in: validate provider + redirect_url, then challenge the provider ──
        ext.MapGet("/challenge/{provider}", async (
            string provider, string? redirect_url,
            SignInManager<StoreUser> signInManager, IOptions<EmailOptions> email, HttpContext ctx) =>
        {
            var scheme = await ResolveSchemeAsync(signInManager, provider).ConfigureAwait(false);
            if (scheme is null) return Results.BadRequest(new { error = "Unknown or unconfigured provider.", code = "Auth.UnknownProvider" });

            var webBase = email.Value.WebBaseUrl.TrimEnd('/');
            var webRedirect = SafeRedirect(redirect_url, webBase);
            // Provider returns to {provider}-callback (middleware), which then redirects here:
            var dispatch = $"/v1/auth/external/callback?redirect_url={Uri.EscapeDataString(webRedirect)}";
            var props = signInManager.ConfigureExternalAuthenticationProperties(scheme, dispatch);
            return Results.Challenge(props, new[] { scheme });
        });

        // ── 2. Dispatch: provider cookie is set → find/link/create → 302 to web with one-time code ──
        ext.MapGet("/callback", async (
            string? redirect_url, IMediator mediator, IExternalAuthCodeStore codes,
            IOptions<EmailOptions> email, HttpContext ctx, CancellationToken ct) =>
        {
            var webBase = email.Value.WebBaseUrl.TrimEnd('/');
            var webRedirect = SafeRedirect(redirect_url, webBase);

            var result = await mediator.Send(new ExternalLoginCallbackCommand(ctx), ct).ConfigureAwait(false);
            if (!result.IsSuccess)
                return Results.Redirect($"{webRedirect}?error={Uri.EscapeDataString(result.Error.Code)}");

            var code = codes.Issue(result.Value!);
            return Results.Redirect($"{webRedirect}?code={Uri.EscapeDataString(code)}");
        });

        // ── 3. Exchange the one-time code for the tokens (body, never the URL) ──
        // Also plant the access token as a first-party httpOnly `jwt` cookie. The web reaches the API
        // through a same-origin proxy, so this Set-Cookie is scoped to the web origin (no Domain attr)
        // and rides SameSite=Strict — surviving a page reload after the in-memory bearer is gone. The
        // body token still drives the immediate in-memory bearer; the cookie is the reload fallback.
        ext.MapPost("/exchange", (ExchangeRequest req, IExternalAuthCodeStore codes, IJwtTokenService jwt, HttpContext ctx) =>
        {
            var auth = codes.Consume(req.Code);
            if (auth is null)
                return Results.BadRequest(new { error = "Invalid or expired code.", code = "Auth.InvalidExchangeCode" });
            jwt.SetSecureCookie(ctx, auth.Token);
            return Results.Ok(auth);
        });

        // Apple Sign-In is NOT wired. It is the only provider requiring a paid Apple Developer
        // membership plus a signed client-secret JWT that expires every 6 months — an operational
        // renewal the store has no process for, and a silent total social-login outage when missed.
        // Google covers the buyer population; revisit if a native iOS app ships (Apple then
        // MANDATES it alongside any other social login).

        // ── 4. Which providers are live (configured) — UI renders only these ──
        ext.MapGet("/providers", async (SignInManager<StoreUser> signInManager) =>
        {
            var schemes = await signInManager.GetExternalAuthenticationSchemesAsync().ConfigureAwait(false);
            var providers = schemes
                .Select(s => new { name = s.Name, display_name = s.DisplayName ?? s.Name })
                .ToList();
            return Results.Ok(new { providers });
        });

        // ── 5. Linking (Settings) — D9 link-ticket pattern ──
        // 5a. bearer POST mints a single-use ticket + the full-page start URL.
        ext.MapPost("/link/{provider}", async (
            string provider, SignInManager<StoreUser> signInManager, IExternalAuthCodeStore codes,
            IOptions<EmailOptions> email, ClaimsPrincipal user) =>
        {
            var scheme = await ResolveSchemeAsync(signInManager, provider).ConfigureAwait(false);
            if (scheme is null) return Results.BadRequest(new { error = "Unknown or unconfigured provider.", code = "Auth.UnknownProvider" });

            var ticket = codes.IssueLinkTicket(user.UserId());
            var webBase = email.Value.WebBaseUrl.TrimEnd('/');
            var start = $"/v1/auth/external/link/{scheme}/start?ticket={Uri.EscapeDataString(ticket)}"
                      + $"&redirect_url={Uri.EscapeDataString(webBase)}";
            return Results.Ok(new { start_url = start });
        }).RequireAuthorization();

        // 5b. anon full-page nav: resolve ticket → stash user id in external props → challenge.
        ext.MapGet("/link/{provider}/start", async (
            string provider, string ticket, string? redirect_url,
            SignInManager<StoreUser> signInManager, IExternalAuthCodeStore codes, IOptions<EmailOptions> email) =>
        {
            var scheme = await ResolveSchemeAsync(signInManager, provider).ConfigureAwait(false);
            if (scheme is null) return Results.BadRequest(new { error = "Unknown or unconfigured provider.", code = "Auth.UnknownProvider" });

            var userId = codes.ConsumeLinkTicket(ticket);
            if (userId is null) return Results.BadRequest(new { error = "Invalid or expired link ticket.", code = "Auth.InvalidLinkTicket" });

            var webBase = email.Value.WebBaseUrl.TrimEnd('/');
            var webRedirect = SafeRedirect(redirect_url, webBase);
            var linkCallback = $"/v1/auth/external/link-callback?redirect_url={Uri.EscapeDataString(webRedirect)}";
            var props = signInManager.ConfigureExternalAuthenticationProperties(scheme, linkCallback);
            props.Items["link_user_id"] = userId.Value.ToString();
            return Results.Challenge(props, new[] { scheme });
        });

        // 5c. anon link round-trip return: read user id back from external props → link.
        ext.MapGet("/link-callback", async (
            string? redirect_url, IMediator mediator, IOptions<EmailOptions> email, HttpContext ctx, CancellationToken ct) =>
        {
            var webBase = email.Value.WebBaseUrl.TrimEnd('/');
            var webRedirect = SafeRedirect(redirect_url, webBase);

            var authResult = await ctx.AuthenticateAsync(IdentityConstants.ExternalScheme).ConfigureAwait(false);
            if (authResult.Properties is null ||
                !authResult.Properties.Items.TryGetValue("link_user_id", out var idStr) ||
                !Guid.TryParse(idStr, out var userId))
            {
                return Results.Redirect($"{webRedirect}?error=Auth.LinkFailed");
            }

            var result = await mediator.Send(new LinkExternalLoginCommand(userId), ct).ConfigureAwait(false);
            return result.IsSuccess
                ? Results.Redirect($"{webRedirect}?linked=1")
                : Results.Redirect($"{webRedirect}?error={Uri.EscapeDataString(result.Error.Code)}");
        });

        // ── 6. Unlink (bearer) — handler blocks removing the only credential ──
        ext.MapDelete("/unlink/{provider}", async (
            string provider, IMediator mediator, ClaimsPrincipal user, CancellationToken ct) =>
        {
            var result = await mediator.Send(new UnlinkExternalLoginCommand(user.UserId(), provider), ct).ConfigureAwait(false);
            return result.IsSuccess ? Results.Ok(new { message = "Disconnected." }) : result.Error.ToHttp();
        }).RequireAuthorization();

        // ── 7. Linked providers (bearer) — Settings UI ──
        ext.MapGet("/logins", async (IMediator mediator, ClaimsPrincipal user, CancellationToken ct) =>
        {
            var result = await mediator.Send(new GetUserLoginsQuery(user.UserId()), ct).ConfigureAwait(false);
            return result.IsSuccess ? Results.Ok(result.Value) : result.Error.ToHttp();
        }).RequireAuthorization();

        // No select-role endpoint. The introduction-exchange forced a Buyer/Connector pick on first
        // login and minted a role_pending token that authorised nothing else. The store has exactly
        // one kind of account, so a role-pending state cannot occur and the extra round trip would
        // only be a page a customer has to click through before reaching what they paid for.
    }

    /// <summary>Maps a route token ("google"/"linkedin") to a registered external scheme name, or null
    /// if the provider isn't wired (empty ClientId) — drives the "button absent / 400" behaviour.</summary>
    private static async Task<string?> ResolveSchemeAsync(SignInManager<StoreUser> signInManager, string provider)
    {
        if (string.IsNullOrWhiteSpace(provider)) return null;
        var schemes = await signInManager.GetExternalAuthenticationSchemesAsync().ConfigureAwait(false);
        return schemes.FirstOrDefault(s =>
            string.Equals(s.Name, provider, StringComparison.OrdinalIgnoreCase))?.Name;
    }

    /// <summary>Open-redirect guard: only allow absolute URLs sharing the web origin; otherwise fall
    /// back to the default callback page. Never redirect off-origin.</summary>
    private static string SafeRedirect(string? candidate, string webBase)
    {
        var fallback = $"{webBase}/auth/callback";
        if (string.IsNullOrWhiteSpace(candidate)) return fallback;
        if (!Uri.TryCreate(candidate, UriKind.Absolute, out var url)) return fallback;
        if (!Uri.TryCreate(webBase, UriKind.Absolute, out var baseUri)) return fallback;
        return string.Equals(url.Scheme, baseUri.Scheme, StringComparison.OrdinalIgnoreCase)
            && string.Equals(url.Authority, baseUri.Authority, StringComparison.OrdinalIgnoreCase)
            ? candidate
            : fallback;
    }
}
