using System.IdentityModel.Tokens.Jwt;
using FluentValidation;
using MediatR;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Identity;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Store.Catalog.Domain.Identity;
using Store.Api.Common;
using Store.Api.Common.Audit;

namespace Store.Api.Identity;

public sealed record LoginCommand(
    string Username,
    string Password,
    HttpContext HttpContext) : IRequest<Result<AuthResponseDto>>;

public sealed class LoginCommandValidator : AbstractValidator<LoginCommand>
{
    public LoginCommandValidator()
    {
        RuleFor(x => x.Username).NotEmpty();
        RuleFor(x => x.Password).NotEmpty();
    }
}

internal sealed class LoginCommandHandler : IRequestHandler<LoginCommand, Result<AuthResponseDto>>
{
    private readonly UserManager<StoreUser> _userManager;
    private readonly SignInManager<StoreUser> _signInManager;
    private readonly IJwtTokenService _jwtTokenService;
    private readonly IRefreshTokenService _refreshTokenService;
    private readonly JwtOptions _jwtOptions;
    private readonly IAuditLogger _auditLogger;

    public LoginCommandHandler(
        UserManager<StoreUser> userManager,
        SignInManager<StoreUser> signInManager,
        IJwtTokenService jwtTokenService,
        IRefreshTokenService refreshTokenService,
        IOptions<JwtOptions> jwtOptions,
        IAuditLogger auditLogger)
    {
        _userManager = userManager;
        _signInManager = signInManager;
        _jwtTokenService = jwtTokenService;
        _refreshTokenService = refreshTokenService;
        _jwtOptions = jwtOptions.Value;
        _auditLogger = auditLogger;
    }

    public async Task<Result<AuthResponseDto>> Handle(LoginCommand request, CancellationToken cancellationToken)
    {
        var correlationId = request.HttpContext.GetCorrelationId();
        var ipAddress = request.HttpContext.GetClientIpAddress();
        var userAgent = request.HttpContext.GetUserAgent();

        var user = await _userManager.FindByNameAsync(request.Username).ConfigureAwait(false);
        if (user is null)
        {
            await LogFailureAsync(AuditActions.LoginFailed, string.Empty, $"User:{request.Username}", "StoreUser not found", ipAddress, userAgent, correlationId, cancellationToken).ConfigureAwait(false);
            return Result.Failure<AuthResponseDto>(Error.Auth.InvalidCredentials);
        }

        if (await _userManager.IsLockedOutAsync(user).ConfigureAwait(false))
        {
            await LogFailureAsync(AuditActions.LoginFailed, user.Id.ToString(), $"User:{user.Id}", "Account locked", ipAddress, userAgent, correlationId, cancellationToken).ConfigureAwait(false);
            return Result.Failure<AuthResponseDto>(Error.Auth.AccountLocked(AuthConstants.LockoutDurationMinutes));
        }

        var signInResult = await _signInManager.CheckPasswordSignInAsync(user, request.Password, lockoutOnFailure: true).ConfigureAwait(false);

        if (signInResult.IsLockedOut)
        {
            await LogFailureAsync(AuditActions.AccountLockout, user.Id.ToString(), $"User:{user.Id}", "Locked after failed attempts", ipAddress, userAgent, correlationId, cancellationToken).ConfigureAwait(false);
            return Result.Failure<AuthResponseDto>(Error.Auth.AccountLocked(AuthConstants.LockoutDurationMinutes));
        }

        if (!signInResult.Succeeded)
        {
            await LogFailureAsync(AuditActions.LoginFailed, user.Id.ToString(), $"User:{user.Id}", "Invalid password", ipAddress, userAgent, correlationId, cancellationToken).ConfigureAwait(false);
            return Result.Failure<AuthResponseDto>(Error.Auth.InvalidCredentials);
        }

        await _userManager.ResetAccessFailedCountAsync(user).ConfigureAwait(false);

        if (!user.IsActive)
        {
            await LogFailureAsync(AuditActions.LoginFailed, user.Id.ToString(), $"User:{user.Id}", "Account deactivated", ipAddress, userAgent, correlationId, cancellationToken).ConfigureAwait(false);
            return Result.Failure<AuthResponseDto>(Error.Auth.AccountDeactivated);
        }

        if (!user.EmailConfirmed)
        {
            await LogFailureAsync(AuditActions.LoginFailed, user.Id.ToString(), $"User:{user.Id}", "Email not verified", ipAddress, userAgent, correlationId, cancellationToken).ConfigureAwait(false);
            return Result.Failure<AuthResponseDto>(new Error("Auth.EmailNotVerified", "Please verify your email before logging in.", ErrorType.Validation));
        }

        var token = await _jwtTokenService.GenerateTokenAsync(
            user, DateTime.UtcNow.AddMinutes(_jwtOptions.TokenExpiryMinutes), cancellationToken).ConfigureAwait(false);
        var refresh = await _refreshTokenService.GenerateRefreshTokenAsync(
            user.Id.ToString(), request.HttpContext.GetUserAgent(), request.HttpContext.GetClientIpAddress(), token.Id, cancellationToken).ConfigureAwait(false);
        _jwtTokenService.SetSecureCookie(request.HttpContext, token);

        await _auditLogger.LogAsync(new AuditEvent
        {
            Action = AuditActions.Login,
            UserId = user.Id.ToString(),
            Resource = $"User:{user.Id}",
            IsSuccess = true,
            IpAddress = ipAddress,
            UserAgent = userAgent,
            CorrelationId = correlationId
        }, cancellationToken).ConfigureAwait(false);

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

    private Task LogFailureAsync(string action, string userId, string resource, string details,
        string ip, string ua, string correlationId, CancellationToken ct) =>
        _auditLogger.LogAsync(new AuditEvent
        {
            Action = action,
            UserId = userId,
            Resource = resource,
            IsSuccess = false,
            Details = details,
            IpAddress = ip,
            UserAgent = ua,
            CorrelationId = correlationId
        }, ct);
}
