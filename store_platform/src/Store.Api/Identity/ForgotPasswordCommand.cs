using FluentValidation;
using MediatR;
using Microsoft.AspNetCore.Identity;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Store.Api.Common;
using Store.Catalog.Domain.Identity;
using Store.Api.Common.Audit;

namespace Store.Api.Identity;

public sealed record ForgotPasswordCommand(string Email) : IRequest<Result>;

public sealed class ForgotPasswordCommandValidator : AbstractValidator<ForgotPasswordCommand>
{
    public ForgotPasswordCommandValidator()
    {
        RuleFor(x => x.Email).NotEmpty().EmailAddress();
    }
}

internal sealed class ForgotPasswordCommandHandler : IRequestHandler<ForgotPasswordCommand, Result>
{
    private readonly UserManager<StoreUser> _userManager;
    private readonly IAuditLogger _auditLogger;
    private readonly ITransactionalEmailSender _emailSender;
    private readonly EmailOptions _emailOptions;
    private readonly ILogger<ForgotPasswordCommandHandler> _logger;

    public ForgotPasswordCommandHandler(
        UserManager<StoreUser> userManager,
        IAuditLogger auditLogger,
        ITransactionalEmailSender emailSender,
        IOptions<EmailOptions> emailOptions,
        ILogger<ForgotPasswordCommandHandler> logger)
    {
        _userManager = userManager;
        _auditLogger = auditLogger;
        _emailSender = emailSender;
        _emailOptions = emailOptions.Value;
        _logger = logger;
    }

    public async Task<Result> Handle(ForgotPasswordCommand request, CancellationToken cancellationToken)
    {
        var user = await _userManager.FindByEmailAsync(request.Email).ConfigureAwait(false);
        
        // Timing-safe: always perform some work and return Success to prevent enumeration.
        if (user == null || !user.IsActive)
        {
            _logger.LogWarning("Forgot password requested for non-existent or inactive email: {Email}", request.Email);
            // Simulate token generation time
            await Task.Delay(Random.Shared.Next(50, 150), cancellationToken).ConfigureAwait(false);
            return Result.Success();
        }

        var token = await _userManager.GeneratePasswordResetTokenAsync(user).ConfigureAwait(false);

        // Send the reset email. Non-throwing sender (no-ops to a log when unconfigured) keeps this
        // timing-safe and never reveals a provider error that could distinguish a real account.
        var resetLink = EmailTemplates.PasswordResetLink(_emailOptions.WebBaseUrl, user.Email!, token);
        var (subject, html) = EmailTemplates.PasswordReset(resetLink);
        await _emailSender.SendAsync(user.Email!, subject, html, cancellationToken).ConfigureAwait(false);

        await _auditLogger.LogAsync(new AuditEvent
        {
            Action = AuditActions.PasswordReset,
            UserId = user.Id.ToString(),
            Resource = $"User:{user.Id}",
            IsSuccess = true,
            Details = "Password reset token generated"
        }, cancellationToken).ConfigureAwait(false);

        return Result.Success();
    }
}
