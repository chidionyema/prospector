using System.Globalization;
using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using MediatR;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;
using Store.Api.Common;
using Store.Api.Common.Audit;

namespace Store.Api.Identity;

public sealed record LogoutCommand(ClaimsPrincipal User, HttpContext HttpContext) : IRequest<Result>;

internal sealed class LogoutCommandHandler : IRequestHandler<LogoutCommand, Result>
{
    private readonly IJwtTokenService _jwtTokenService;
    private readonly ITokenRevocationService _revocationService;
    private readonly IRefreshTokenService _refreshTokenService;
    private readonly IAuditLogger _auditLogger;

    public LogoutCommandHandler(
        IJwtTokenService jwtTokenService,
        ITokenRevocationService revocationService,
        IRefreshTokenService refreshTokenService,
        IAuditLogger auditLogger)
    {
        _jwtTokenService = jwtTokenService;
        _revocationService = revocationService;
        _refreshTokenService = refreshTokenService;
        _auditLogger = auditLogger;
    }

    public async Task<Result> Handle(LogoutCommand request, CancellationToken cancellationToken)
    {
        var userId = request.User.FindFirstValue(ClaimTypes.NameIdentifier) ?? request.User.FindFirstValue("sub");
        var jti = request.User.FindFirstValue(JwtRegisteredClaimNames.Jti);
        var expClaim = request.User.FindFirstValue(JwtRegisteredClaimNames.Exp);

        if (!string.IsNullOrEmpty(jti) && !string.IsNullOrEmpty(userId))
        {
            var expiry = expClaim is not null && long.TryParse(expClaim, NumberStyles.Integer, CultureInfo.InvariantCulture, out var unix)
                ? DateTimeOffset.FromUnixTimeSeconds(unix).UtcDateTime
                : DateTime.UtcNow.AddHours(1);
            await _revocationService.RevokeTokenAsync(jti, userId, expiry, cancellationToken).ConfigureAwait(false);
        }

        if (!string.IsNullOrEmpty(userId))
            await _refreshTokenService.RevokeRefreshTokensForUserAsync(userId, cancellationToken).ConfigureAwait(false);

        _jwtTokenService.DeleteAuthCookie(request.HttpContext);

        await _auditLogger.LogAsync(new AuditEvent
        {
            Action = AuditActions.Logout,
            UserId = userId ?? string.Empty,
            Resource = $"User:{userId}",
            IsSuccess = true
        }, cancellationToken).ConfigureAwait(false);

        return Result.Success();
    }
}
