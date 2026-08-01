using FluentValidation;
using MediatR;
using Microsoft.AspNetCore.Identity;
using Store.Catalog.Domain.Identity;
using Store.Api.Common;
using Store.Api.Common.Audit;

namespace Store.Api.Identity;

/// <summary>Confirms a user's email from the token minted at registration / resend.
/// Idempotent: a second call for an already-verified account succeeds without re-confirming.</summary>
public sealed record VerifyEmailCommand(string UserId, string Token) : IRequest<Result>;

public sealed class VerifyEmailCommandValidator : AbstractValidator<VerifyEmailCommand>
{
    public VerifyEmailCommandValidator()
    {
        RuleFor(x => x.UserId).NotEmpty();
        RuleFor(x => x.Token).NotEmpty();
    }
}

internal sealed class VerifyEmailCommandHandler : IRequestHandler<VerifyEmailCommand, Result>
{
    private readonly UserManager<StoreUser> _userManager;
    private readonly IAuditLogger _auditLogger;

    public VerifyEmailCommandHandler(UserManager<StoreUser> userManager, IAuditLogger auditLogger)
    {
        _userManager = userManager;
        _auditLogger = auditLogger;
    }

    public async Task<Result> Handle(VerifyEmailCommand request, CancellationToken cancellationToken)
    {
        var user = await _userManager.FindByIdAsync(request.UserId).ConfigureAwait(false);

        // Anti-enumeration: a bad userId is indistinguishable from a bad token (both → generic 400).
        if (user is null || !user.IsActive)
            return Result.Failure(new Error("Auth.EmailVerifyFailed", "Invalid or expired verification link.", ErrorType.Validation));

        // Already verified → idempotent success (the link may be opened twice).
        if (user.EmailConfirmed)
            return Result.Success();

        var result = await _userManager.ConfirmEmailAsync(user, request.Token).ConfigureAwait(false);
        if (!result.Succeeded)
            return Result.Failure(new Error("Auth.EmailVerifyFailed", "Invalid or expired verification link.", ErrorType.Validation));

        await _auditLogger.LogAsync(new AuditEvent
        {
            Action = AuditActions.EmailVerify,
            UserId = user.Id.ToString(),
            Resource = $"User:{user.Id}",
            IsSuccess = true,
            Details = "Email verified via token"
        }, cancellationToken).ConfigureAwait(false);

        return Result.Success();
    }
}
