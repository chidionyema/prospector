using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Text.RegularExpressions;
using MediatR;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Identity;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Store.Api.Common;
using Store.Catalog.Domain.Identity;

namespace Store.Api.Identity;

/// <summary>
/// Completes a Google/LinkedIn sign-in after the provider redirect (E16). Dispatched by the
/// <c>/v1/auth/external/callback</c> endpoint once ASP.NET has populated the external login
/// cookie. Find → link → or create, then mints the same <see cref="AuthResponseDto"/> password
/// login returns. A brand-new user is created <b>role-less</b> (D4) so the token is role-pending
/// and the web app routes them to choose-role. Reference: haworks
/// Identity.Application/ExternalLoginCallbackCommand.cs — adapted to TIE's Guid identity,
/// consolidation by verified email (D3), IResilientTransaction (D7), and no auto-role.
/// </summary>
public sealed record ExternalLoginCallbackCommand(HttpContext HttpContext) : IRequest<Result<AuthResponseDto>>;

/// <summary>Tunables for external-login behaviour (email-verification trust + username shaping).</summary>
public sealed class ExternalLoginOptions
{
    /// <summary>
    /// Providers trusted to have verified the email as part of their own flow, even absent an
    /// explicit <c>email_verified</c> claim. Google OAuth and LinkedIn OIDC both also send the
    /// claim, so this is a belt-and-braces fallback (E16 D2).
    /// </summary>
    public string[] TrustedEmailProviders { get; init; } = ["Google", "LinkedIn"];

    public string AllowedUserNameCharacters { get; init; } =
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_";

    public int MaxUserNameLength { get; init; } = 50;
}

internal sealed class ExternalLoginCallbackCommandHandler
    : IRequestHandler<ExternalLoginCallbackCommand, Result<AuthResponseDto>>
{
    private readonly SignInManager<StoreUser> _signInManager;
    private readonly UserManager<StoreUser> _userManager;
    private readonly IJwtTokenService _jwtTokenService;
    private readonly IRefreshTokenService _refreshTokenService;
    private readonly IResilientTransaction _transaction;
    private readonly ILogger<ExternalLoginCallbackCommandHandler> _logger;
    private readonly JwtOptions _jwtOptions;
    private readonly ExternalLoginOptions _options;

    public ExternalLoginCallbackCommandHandler(
        SignInManager<StoreUser> signInManager,
        UserManager<StoreUser> userManager,
        IJwtTokenService jwtTokenService,
        IRefreshTokenService refreshTokenService,
        IResilientTransaction transaction,
        ILogger<ExternalLoginCallbackCommandHandler> logger,
        IOptions<JwtOptions> jwtOptions,
        IOptions<ExternalLoginOptions>? options = null)
    {
        _signInManager = signInManager;
        _userManager = userManager;
        _jwtTokenService = jwtTokenService;
        _refreshTokenService = refreshTokenService;
        _transaction = transaction;
        _logger = logger;
        _jwtOptions = jwtOptions.Value;
        _options = options?.Value ?? new ExternalLoginOptions();
    }

    public async Task<Result<AuthResponseDto>> Handle(
        ExternalLoginCallbackCommand request, CancellationToken cancellationToken)
    {
        var loginInfo = await _signInManager.GetExternalLoginInfoAsync().ConfigureAwait(false);
        if (loginInfo is null)
            return Result.Failure<AuthResponseDto>(Error.Auth.ExternalLoginFailed);

        if (string.IsNullOrWhiteSpace(loginInfo.ProviderKey))
            return Result.Failure<AuthResponseDto>(Error.Auth.InvalidProviderKey);

        // 1. Returning, already-linked user → straight in (token tier follows role presence, §0.3).
        var byLogin = await _userManager.FindByLoginAsync(loginInfo.LoginProvider, loginInfo.ProviderKey).ConfigureAwait(false);
        if (byLogin is not null)
        {
            if (!byLogin.IsActive)
                return Result.Failure<AuthResponseDto>(Error.Auth.AccountDeactivated);

            _logger.LogInformation("External login {Provider} resolved to existing user {UserId}.",
                loginInfo.LoginProvider, byLogin.Id);
            return await GenerateAuthResponseAsync(byLogin, request.HttpContext, cancellationToken).ConfigureAwait(false);
        }

        // 2. Need an email to consolidate or create.
        var email = loginInfo.Principal.FindFirstValue(ClaimTypes.Email);
        if (string.IsNullOrWhiteSpace(email))
        {
            _logger.LogWarning("Provider {Provider} returned no email claim.", loginInfo.LoginProvider);
            return Result.Failure<AuthResponseDto>(Error.Auth.MissingEmail);
        }

        // 3. Anti-hijack gate (D2): only link/create when the provider verified the email.
        if (!IsEmailVerified(loginInfo))
        {
            _logger.LogWarning("Provider {Provider} returned an unverified email; refusing to link.",
                loginInfo.LoginProvider);
            return Result.Failure<AuthResponseDto>(Error.Auth.UnverifiedEmail);
        }

        // 4. Consolidation (§0.4 first bullet, D3): an existing account on the SAME anti-Sybil key
        //    (the key register dedups on) → auto-link the provider and sign in. Verified-email gate
        //    above is what makes silent linking safe.
        // Matches Identity's default UpperInvariantLookupNormalizer, which is what wrote
        // the NormalizedEmail column this query filters on.
        var normalizedEmail = email.ToUpperInvariant();
        var byEmail = _userManager.Users.FirstOrDefault(u => u.NormalizedEmail == normalizedEmail);
        if (byEmail is not null)
        {
            if (!byEmail.IsActive)
                return Result.Failure<AuthResponseDto>(Error.Auth.AccountDeactivated);

            var link = await _userManager.AddLoginAsync(byEmail, loginInfo).ConfigureAwait(false);
            if (!link.Succeeded)
            {
                _logger.LogWarning("Failed to auto-link {Provider} to user {UserId}: {Errors}",
                    loginInfo.LoginProvider, byEmail.Id,
                    string.Join(", ", link.Errors.Select(e => e.Description)));
                return Result.Failure<AuthResponseDto>(Error.Auth.LinkFailed);
            }

            // The provider just verified ownership of this email — confirm it on the account if it
            // was a never-verified password signup (§0.4: link sets EmailConfirmed = true).
            if (!byEmail.EmailConfirmed)
            {
                byEmail.EmailConfirmed = true;
                await _userManager.UpdateAsync(byEmail).ConfigureAwait(false);
            }

            _logger.LogInformation("Auto-linked {Provider} to existing user {UserId} by verified email.",
                loginInfo.LoginProvider, byEmail.Id);
            return await GenerateAuthResponseAsync(byEmail, request.HttpContext, cancellationToken).ConfigureAwait(false);
        }

        // 5. No existing account → create one, ROLE-LESS (D4). select-role assigns Buyer/Connector.
        return await CreateNewUserAsync(loginInfo, email, normalizedEmail, request.HttpContext, cancellationToken).ConfigureAwait(false);
    }

    private async Task<Result<AuthResponseDto>> CreateNewUserAsync(
        ExternalLoginInfo loginInfo, string email, string normalizedEmail,
        HttpContext httpContext, CancellationToken cancellationToken)
    {
        var rawName = loginInfo.Principal.FindFirstValue(ClaimTypes.Name) ?? email.Split('@')[0];
        var userName = await GetUniqueUserNameAsync(SanitizeUserName(rawName)).ConfigureAwait(false);

        var user = new StoreUser
        {
            UserName = userName,
            Email = email,
            EmailConfirmed = true // verified by the external provider (gated above)
        };

        IdentityResult? createResult = null;
        var linked = false;
        await _transaction.ExecuteAsync(async _ =>
        {
            createResult = await _userManager.CreateAsync(user).ConfigureAwait(false);
            if (!createResult.Succeeded) return false;

            var link = await _userManager.AddLoginAsync(user, loginInfo).ConfigureAwait(false);
            if (!link.Succeeded) return false; // rolls back the create
            linked = true;
            // NB: deliberately NO AddToRoleAsync — the user is role-pending until select-role.
            return true;
        }, cancellationToken).ConfigureAwait(false);

        if (createResult is { Succeeded: true } && linked)
        {
            _logger.LogInformation("Created role-less user {UserId} from {Provider}.", user.Id, loginInfo.LoginProvider);
            return await GenerateAuthResponseAsync(user, httpContext, cancellationToken).ConfigureAwait(false);
        }

        // Race: a concurrent first-click created the account between our lookup and create.
        // Re-resolve by the same anti-Sybil key and link onto it (idempotent single account).
        if (createResult is not null &&
            createResult.Errors.Any(e =>
                string.Equals(e.Code, "DuplicateEmail", StringComparison.Ordinal) ||
                string.Equals(e.Code, "DuplicateUserName", StringComparison.Ordinal)))
        {
            var winner = _userManager.Users.FirstOrDefault(u => u.NormalizedEmail == normalizedEmail);
            if (winner is not null)
            {
                var link = await _userManager.AddLoginAsync(winner, loginInfo).ConfigureAwait(false);
                if (link.Succeeded)
                {
                    _logger.LogWarning("Race resolved: linked {Provider} to user {UserId} created concurrently.",
                        loginInfo.LoginProvider, winner.Id);
                    return await GenerateAuthResponseAsync(winner, httpContext, cancellationToken).ConfigureAwait(false);
                }
            }

            // Pure username collision (different person, same display name) — retry once with a fresh name.
            if (winner is null)
            {
                var retryName = await GetUniqueUserNameAsync(SanitizeUserName(
                    loginInfo.Principal.FindFirstValue(ClaimTypes.Name) ?? email.Split('@')[0])).ConfigureAwait(false);
                var retry = new StoreUser
                {
                    UserName = retryName, Email = email, EmailConfirmed = true
                };
                if ((await _userManager.CreateAsync(retry).ConfigureAwait(false)).Succeeded &&
                    (await _userManager.AddLoginAsync(retry, loginInfo).ConfigureAwait(false)).Succeeded)
                {
                    return await GenerateAuthResponseAsync(retry, httpContext, cancellationToken).ConfigureAwait(false);
                }
                await _userManager.DeleteAsync(retry).ConfigureAwait(false);
            }
        }

        _logger.LogWarning("Failed to create user from {Provider}: {Errors}", loginInfo.LoginProvider,
            createResult is null ? "(none)" : string.Join(", ", createResult.Errors.Select(e => e.Description)));
        return Result.Failure<AuthResponseDto>(Error.Auth.CreateFailed);
    }

    private bool IsEmailVerified(ExternalLoginInfo loginInfo)
    {
        var claim = loginInfo.Principal.FindFirst("email_verified")
            ?? loginInfo.Principal.FindFirst("verified_email");
        if (claim is not null && string.Equals(claim.Value, "true", StringComparison.OrdinalIgnoreCase))
            return true;

        return _options.TrustedEmailProviders.Contains(loginInfo.LoginProvider, StringComparer.OrdinalIgnoreCase);
    }

    private string SanitizeUserName(string raw)
    {
        if (string.IsNullOrWhiteSpace(raw)) return "user";
        var pattern = $"[^{Regex.Escape(_options.AllowedUserNameCharacters)}]";
        var sanitized = Regex.Replace(raw, pattern, "", RegexOptions.NonBacktracking);
        if (string.IsNullOrWhiteSpace(sanitized)) sanitized = "user";
        if (sanitized.Length > _options.MaxUserNameLength) sanitized = sanitized[.._options.MaxUserNameLength];
        return sanitized;
    }

    private async Task<string> GetUniqueUserNameAsync(string baseName)
    {
        var userName = baseName;
        var counter = 1;
        while (await _userManager.FindByNameAsync(userName).ConfigureAwait(false) is not null)
        {
            userName = counter > 100
                ? $"{baseName}_{Guid.NewGuid():N}"[..Math.Min(20, _options.MaxUserNameLength)]
                : $"{baseName}{counter++}";
            if (userName.Length > _options.MaxUserNameLength) userName = userName[.._options.MaxUserNameLength];
        }
        return userName;
    }

    private async Task<Result<AuthResponseDto>> GenerateAuthResponseAsync(
        StoreUser user, HttpContext httpContext, CancellationToken cancellationToken)
    {
        var token = await _jwtTokenService.GenerateTokenAsync(
            user, DateTime.UtcNow.AddMinutes(_jwtOptions.TokenExpiryMinutes), cancellationToken).ConfigureAwait(false);
        var refresh = await _refreshTokenService.GenerateRefreshTokenAsync(
            user.Id.ToString(), httpContext.GetUserAgent(), httpContext.GetClientIpAddress(), token.Id, cancellationToken).ConfigureAwait(false);
        _jwtTokenService.SetSecureCookie(httpContext, token);

        return Result.Success(new AuthResponseDto
        {
            Token = new JwtSecurityTokenHandler().WriteToken(token),
            RefreshToken = refresh.Token,
            UserId = user.Id.ToString(),
            Username = user.UserName,
            Email = user.Email,
            Expires = token.ValidTo
        });
    }
}
