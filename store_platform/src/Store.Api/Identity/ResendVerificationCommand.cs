using FluentValidation;
using MediatR;
using Microsoft.AspNetCore.Identity;
using Microsoft.Extensions.Options;
using Store.Api.Common;
using Store.Catalog.Domain.Identity;
using Store.Api.Common.Audit;

namespace Store.Api.Identity;

/// <summary>Re-issues an email-verification token. Anti-enumeration: always returns success and
/// spends comparable time whether or not the email maps to an unverified account.</summary>
public sealed record ResendVerificationCommand(string Email) : IRequest<Result>;

public sealed class ResendVerificationCommandValidator : AbstractValidator<ResendVerificationCommand>
{
    public ResendVerificationCommandValidator()
    {
        RuleFor(x => x.Email).NotEmpty().EmailAddress();
    }
}

internal sealed class ResendVerificationCommandHandler : IRequestHandler<ResendVerificationCommand, Result>
{
    private readonly UserManager<StoreUser> _userManager;
    private readonly IAuditLogger _auditLogger;
    private readonly ITransactionalEmailSender _emailSender;
    private readonly EmailOptions _emailOptions;

    public ResendVerificationCommandHandler(
        UserManager<StoreUser> userManager,
        IAuditLogger auditLogger,
        ITransactionalEmailSender emailSender,
        IOptions<EmailOptions> emailOptions)
    {
        _userManager = userManager;
        _auditLogger = auditLogger;
        _emailSender = emailSender;
        _emailOptions = emailOptions.Value;
    }

    public async Task<Result> Handle(ResendVerificationCommand request, CancellationToken cancellationToken)
    {
        var user = await _userManager.FindByEmailAsync(request.Email).ConfigureAwait(false);

        // Timing-safe: no token for a non-existent, inactive, or already-verified account, but
        // always return Success so callers can't probe which emails are registered/unverified.
        if (user is null || !user.IsActive || user.EmailConfirmed)
        {
            await Task.Delay(Random.Shared.Next(50, 150), cancellationToken).ConfigureAwait(false);
            return Result.Success();
        }

        var token = await _userManager.GenerateEmailConfirmationTokenAsync(user).ConfigureAwait(false);

        // Re-send the verification email. Non-throwing sender (no-ops to a log when unconfigured),
        // so this stays timing-safe and never surfaces a provider error to the caller.
        var verifyLink = EmailTemplates.VerificationLink(_emailOptions.WebBaseUrl, user.Id.ToString(), token);
        var (subject, html) = EmailTemplates.Verification(verifyLink);
        await _emailSender.SendAsync(user.Email!, subject, html, cancellationToken).ConfigureAwait(false);

        await _auditLogger.LogAsync(new AuditEvent
        {
            Action = AuditActions.EmailVerifyResend,
            UserId = user.Id.ToString(),
            Resource = $"User:{user.Id}",
            IsSuccess = true,
            Details = "Email verification token re-issued"
        }, cancellationToken).ConfigureAwait(false);

        return Result.Success();
    }
}
