using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using FluentValidation;
using MediatR;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Identity;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Store.Catalog.Domain.Identity;
using Store.Api.Common;

namespace Store.Api.Identity;

public sealed record RefreshTokenCommand(
    string AccessToken,
    string RefreshToken,
    HttpContext HttpContext) : IRequest<Result<AuthResponseDto>>;

public sealed class RefreshTokenCommandValidator : AbstractValidator<RefreshTokenCommand>
{
    public RefreshTokenCommandValidator()
    {
        RuleFor(x => x.AccessToken).NotEmpty();
        RuleFor(x => x.RefreshToken).NotEmpty();
    }
}

/// <summary>
/// Rotates a refresh token for a fresh access+refresh pair. Validates the (possibly
/// expired) access token's signature, matches the refresh token, enforces expiry,
/// then issues new tokens and deletes the old refresh row (one-time use).
/// Repository access via IRefreshTokenReader to keep Application persistence-agnostic.
/// </summary>
internal sealed class RefreshTokenCommandHandler : IRequestHandler<RefreshTokenCommand, Result<AuthResponseDto>>
{
    private readonly UserManager<StoreUser> _userManager;
    private readonly IJwtTokenService _jwtTokenService;
    private readonly IRefreshTokenService _refreshTokenService;
    private readonly IRefreshTokenReader _refreshTokenReader;
    private readonly JwtOptions _jwtOptions;

    public RefreshTokenCommandHandler(
        UserManager<StoreUser> userManager,
        IJwtTokenService jwtTokenService,
        IRefreshTokenService refreshTokenService,
        IRefreshTokenReader refreshTokenReader,
        IOptions<JwtOptions> jwtOptions)
    {
        _userManager = userManager;
        _jwtTokenService = jwtTokenService;
        _refreshTokenService = refreshTokenService;
        _refreshTokenReader = refreshTokenReader;
        _jwtOptions = jwtOptions.Value;
    }

    public async Task<Result<AuthResponseDto>> Handle(RefreshTokenCommand request, CancellationToken cancellationToken)
    {
        // Validate the access token WITHOUT lifetime — it's expected to be expired.
        var principal = await _jwtTokenService.ValidateTokenAsync(request.AccessToken, validateLifetime: false, cancellationToken).ConfigureAwait(false);
        if (principal is null)
            return Result.Failure<AuthResponseDto>(Error.Auth.InvalidAccessToken);

        var userId = principal.FindFirstValue(ClaimTypes.NameIdentifier) ?? principal.FindFirstValue("sub");
        if (string.IsNullOrEmpty(userId))
            return Result.Failure<AuthResponseDto>(Error.Auth.MissingUserId);

        var stored = await _refreshTokenReader.FindAsync(request.RefreshToken, cancellationToken).ConfigureAwait(false);
        if (stored is null || stored.UserId != Guid.Parse(userId) || stored.IsExpired)
            return Result.Failure<AuthResponseDto>(Error.Auth.InvalidRefreshToken);

        var user = await _userManager.FindByIdAsync(userId).ConfigureAwait(false);
        if (user is null || !user.IsActive)
            return Result.Failure<AuthResponseDto>(Error.Auth.InvalidRefreshToken);

        var token = await _jwtTokenService.GenerateTokenAsync(
            user, DateTime.UtcNow.AddMinutes(_jwtOptions.TokenExpiryMinutes), cancellationToken).ConfigureAwait(false);

        // Rotate: atomically consume THIS refresh token and issue a fresh pair.
        // If the token was already consumed (reuse detection), the rotate method
        // will revoke the entire family and return Success=false.
        var (success, newRefreshToken) = await _refreshTokenService.RotateRefreshTokenAsync(
            request.RefreshToken, request.HttpContext.GetUserAgent(), request.HttpContext.GetClientIpAddress(), token.Id, cancellationToken).ConfigureAwait(false);
        if (!success || newRefreshToken == null)
            return Result.Failure<AuthResponseDto>(Error.Auth.InvalidRefreshToken);

        _jwtTokenService.SetSecureCookie(request.HttpContext, token);

        return Result.Success(new AuthResponseDto
        {
            Token = new JwtSecurityTokenHandler().WriteToken(token),
            RefreshToken = newRefreshToken.Token,
            UserId = user.Id.ToString(),
            Username = user.UserName,
            Email = user.Email,
            Expires = token.ValidTo
        });
    }
}

/// <summary>Read-side lookup for a stored refresh token. Implemented in Infrastructure.</summary>
public interface IRefreshTokenReader
{
    Task<RefreshToken?> FindAsync(string token, CancellationToken ct = default);
}
