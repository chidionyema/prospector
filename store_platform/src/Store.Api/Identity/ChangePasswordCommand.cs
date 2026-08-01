using FluentValidation;
using MediatR;
using Microsoft.AspNetCore.Identity;
using Store.Catalog.Domain.Identity;
using Store.Api.Common;
using Store.Api.Common.Audit;

namespace Store.Api.Identity;

public sealed record ChangePasswordCommand(
    Guid UserId,
    string CurrentPassword,
    string NewPassword) : IRequest<Result>;

public sealed class ChangePasswordCommandValidator : AbstractValidator<ChangePasswordCommand>
{
    public ChangePasswordCommandValidator()
    {
        RuleFor(x => x.CurrentPassword).NotEmpty();
        RuleFor(x => x.NewPassword).NotEmpty().MinimumLength(8).MaximumLength(128);
    }
}

internal sealed class ChangePasswordCommandHandler : IRequestHandler<ChangePasswordCommand, Result>
{
    private readonly UserManager<StoreUser> _userManager;
    private readonly IAuditLogger _auditLogger;

    public ChangePasswordCommandHandler(UserManager<StoreUser> userManager, IAuditLogger auditLogger)
    {
        _userManager = userManager;
        _auditLogger = auditLogger;
    }

    public async Task<Result> Handle(ChangePasswordCommand request, CancellationToken cancellationToken)
    {
        var user = await _userManager.FindByIdAsync(request.UserId.ToString()).ConfigureAwait(false);
        if (user == null)
            return Result.Failure(Error.Auth.UserNotFound);

        var result = await _userManager.ChangePasswordAsync(user, request.CurrentPassword, request.NewPassword).ConfigureAwait(false);
        
        if (!result.Succeeded)
        {
            var errors = string.Join(", ", result.Errors.Select(e => e.Description));
            return Result.Failure(new Error("Auth.ChangePasswordFailed", errors, ErrorType.Validation));
        }

        await _auditLogger.LogAsync(new AuditEvent
        {
            Action = AuditActions.PasswordChange,
            UserId = user.Id.ToString(),
            Resource = $"User:{user.Id}",
            IsSuccess = true
        }, cancellationToken).ConfigureAwait(false);

        return Result.Success();
    }
}
