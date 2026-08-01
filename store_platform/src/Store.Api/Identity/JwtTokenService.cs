using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Identity;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Microsoft.IdentityModel.Tokens;
using Store.Api.Identity;
using Store.Catalog.Domain.Identity;

namespace Store.Api.Identity;

/// <summary>
/// JWT generation + validation. Ported from haworks Identity.Infrastructure/
/// JwtTokenService.cs. RS256, key from IJwtSigningKeyProvider (config-backed, no
/// Vault). Includes the JTI revocation check on validation and the httpOnly
/// secure-cookie helpers.
/// </summary>
public sealed class JwtTokenService : IJwtTokenService
{
    private readonly UserManager<StoreUser> _userManager;
    private readonly JwtOptions _jwtOptions;
    private readonly ILogger<JwtTokenService> _logger;
    private readonly ITokenRevocationService _revocationService;
    private readonly IJwtSigningKeyProvider _signingKeyProvider;
    private readonly IHostEnvironment _environment;

    private static readonly string[] RsaSha256Algorithms = { SecurityAlgorithms.RsaSha256 };

    public JwtTokenService(
        UserManager<StoreUser> userManager,
        IOptions<JwtOptions> jwtOptions,
        ILogger<JwtTokenService> logger,
        ITokenRevocationService revocationService,
        IJwtSigningKeyProvider signingKeyProvider,
        IHostEnvironment environment)
    {
        _userManager = userManager;
        _jwtOptions = jwtOptions.Value;
        _logger = logger;
        _revocationService = revocationService;
        _signingKeyProvider = signingKeyProvider;
        _environment = environment;
    }

    public async Task<JwtSecurityToken> GenerateTokenAsync(StoreUser user, DateTime expiration, CancellationToken ct = default)
    {
        var claims = new List<Claim>
        {
            new(JwtRegisteredClaimNames.Sub, user.Id.ToString()),
            new(ClaimTypes.NameIdentifier, user.Id.ToString()),
            new(ClaimTypes.Name, user.UserName!),
            new(JwtRegisteredClaimNames.Jti, Guid.NewGuid().ToString()),
            new(JwtRegisteredClaimNames.Email, user.Email!)
        };

        // No role claims. The introduction-exchange emitted either the user's roles or, for a fresh
        // social signup with none, a "role_pending" claim that authorised nothing but /select-role —
        // it had two kinds of user (Buyer, Connector) and had to make you choose before you could
        // act. The store has one kind: a customer. Every authenticated caller may do exactly the
        // same things, so a role claim would carry no information and role_pending would gate a
        // choice that does not exist. Authorization here is [Authorize] plus ownership checks on
        // the row, not roles. Per-user claims are still carried through in case one is ever added.
        claims.AddRange(await _userManager.GetClaimsAsync(user).ConfigureAwait(false));

        var signingCredentials = new SigningCredentials(_signingKeyProvider.SigningKey, SecurityAlgorithms.RsaSha256);
        var token = new JwtSecurityToken(
            issuer: _jwtOptions.Issuer,
            audience: _jwtOptions.Audience,
            claims: claims,
            expires: expiration,
            signingCredentials: signingCredentials);
        token.Header["kid"] = _signingKeyProvider.KeyId;

        _logger.LogInformation("Token generated for user {UserId} (kid {KeyId})", user.Id, _signingKeyProvider.KeyId);
        return token;
    }

    public async Task<ClaimsPrincipal?> ValidateTokenAsync(string tokenString, bool validateLifetime = true, CancellationToken ct = default)
    {
        if (string.IsNullOrEmpty(tokenString)) return null;

        var tokenHandler = new JwtSecurityTokenHandler();
        ClaimsPrincipal principal;
        try
        {
            principal = tokenHandler.ValidateToken(tokenString, GetTokenValidationParameters(validateLifetime), out _);
        }
        catch (SecurityTokenException ex)
        {
            _logger.LogWarning(ex, "Token validation failed");
            return null;
        }

        var jti = principal.FindFirstValue(JwtRegisteredClaimNames.Jti);
        if (!string.IsNullOrEmpty(jti) && await _revocationService.IsTokenRevokedAsync(jti, ct).ConfigureAwait(false))
        {
            _logger.LogWarning("Token {Jti} has been revoked", jti);
            return null;
        }

        return principal;
    }

    public TokenValidationParameters GetTokenValidationParameters(bool validateLifetime = true) => new()
    {
        ValidateIssuerSigningKey = true,
        IssuerSigningKey = _signingKeyProvider.SigningKey,
        ValidAlgorithms = RsaSha256Algorithms,
        ValidateIssuer = true,
        ValidIssuer = _jwtOptions.Issuer,
        ValidateAudience = true,
        ValidAudience = _jwtOptions.Audience,
        ValidateLifetime = validateLifetime,
        ClockSkew = TimeSpan.FromSeconds(AuthConstants.ClockSkewToleranceSeconds)
    };

    public void SetSecureCookie(HttpContext context, JwtSecurityToken token)
        => AppendJwtCookie(context, new JwtSecurityTokenHandler().WriteToken(token), token.ValidTo);

    // Overload for flows that only hold the serialized token (e.g. the social-login exchange
    // returns a cached AuthResponseDto whose token is a string). Read `exp` off the token so the
    // cookie expires exactly when the token does.
    public void SetSecureCookie(HttpContext context, string tokenString)
        => AppendJwtCookie(context, tokenString, new JwtSecurityTokenHandler().ReadJwtToken(tokenString).ValidTo);

    private void AppendJwtCookie(HttpContext context, string tokenString, DateTime validTo) =>
        context.Response.Cookies.Append("jwt", tokenString, new CookieOptions
        {
            HttpOnly = true,
            Secure = _environment.IsProduction(),
            SameSite = SameSiteMode.Strict,
            Expires = new DateTimeOffset(validTo, TimeSpan.Zero),
            Path = "/",
            IsEssential = true
        });

    public void DeleteAuthCookie(HttpContext context) =>
        context.Response.Cookies.Delete("jwt", new CookieOptions
        {
            HttpOnly = true,
            Secure = _environment.IsProduction(),
            SameSite = SameSiteMode.Strict,
            Path = "/"
        });
}
