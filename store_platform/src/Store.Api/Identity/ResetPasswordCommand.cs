using FluentValidation;
using MediatR;
using Microsoft.AspNetCore.Identity;
using Store.Catalog.Domain.Identity;
using Store.Api.Common;
using Store.Api.Common.Audit;

namespace Store.Api.Identity;

public sealed record ResetPasswordCommand(
    string Email,
    string Token,
    string NewPassword) : IRequest<Result>;

public sealed class ResetPasswordCommandValidator : AbstractValidator<ResetPasswordCommand>
{
    public ResetPasswordCommandValidator()
    {
        RuleFor(x => x.Email).NotEmpty().EmailAddress();
        RuleFor(x => x.Token).NotEmpty();
        RuleFor(x => x.NewPassword).NotEmpty().MinimumLength(8).MaximumLength(128);
    }
}

internal sealed class ResetPasswordCommandHandler : IRequestHandler<ResetPasswordCommand, Result>
{
    private readonly UserManager<StoreUser> _userManager;
    private readonly IAuditLogger _auditLogger;

    public ResetPasswordCommandHandler(UserManager<StoreUser> userManager, IAuditLogger auditLogger)
    {
        _userManager = userManager;
        _auditLogger = auditLogger;
    }

    public async Task<Result> Handle(ResetPasswordCommand request, CancellationToken cancellationToken)
    {
        var user = await _userManager.FindByEmailAsync(request.Email).ConfigureAwait(false);
        
        // Timing-safe: don't leak if user exists or not.
        if (user == null || !user.IsActive)
        {
            // Simulate work time
            await Task.Delay(Random.Shared.Next(50, 150), cancellationToken).ConfigureAwait(false);
            return Result.Success();
        }

        var result = await _userManager.ResetPasswordAsync(user, request.Token, request.NewPassword).ConfigureAwait(false);
        
        if (!result.Succeeded)
        {
            // For security, we might want to return 200 even on failure, 
            // but for reset-token invalidity, 400 is generally acceptable if the email was correct.
            return Result.Failure(new Error("Auth.ResetPasswordFailed", "Invalid token or password requirements not met.", ErrorType.Validation));
        }

        await _auditLogger.LogAsync(new AuditEvent
        {
            Action = AuditActions.PasswordChange,
            UserId = user.Id.ToString(),
            Resource = $"User:{user.Id}",
            IsSuccess = true,
            Details = "Password reset via token successful"
        }, cancellationToken).ConfigureAwait(false);

        return Result.Success();
    }
}
