using System.IdentityModel.Tokens.Jwt;
using FluentValidation;
using MediatR;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Identity;
using Microsoft.Extensions.Options;
using Store.Api.Common;
using Store.Catalog.Domain.Identity;
using Store.Api.Common.Audit;

namespace Store.Api.Identity;

public sealed record RegisterCommand(
    string Username,
    string Email,
    string Password,
    string? TosVersion,
    HttpContext HttpContext) : IRequest<Result<AuthResponseDto>>;

public sealed class RegisterCommandValidator : AbstractValidator<RegisterCommand>
{
    public RegisterCommandValidator()
    {
        RuleFor(x => x.Username).NotEmpty().MinimumLength(3).MaximumLength(50);
        RuleFor(x => x.Email).NotEmpty().EmailAddress();
        // MaximumLength prevents a hash-DoS from an absurdly long password (FIND-18).
        RuleFor(x => x.Password).NotEmpty().MinimumLength(8).MaximumLength(128);
        // No Role rule, because the command carries no role. In the introduction-exchange this
        // validator was a privilege-escalation guard: /v1/auth/register is ANONYMOUS, so a caller
        // who could name their own role could mint an Admin account, and the rule pinned it to the
        // Buyer/Connector allow-list. Deleting the field removes the attack rather than guarding it.
        RuleFor(x => x.TosVersion).NotEmpty();
    }
}

internal sealed class RegisterCommandHandler : IRequestHandler<RegisterCommand, Result<AuthResponseDto>>
{
    private readonly UserManager<StoreUser> _userManager;
    private readonly IAuditLogger _auditLogger;
    private readonly IResilientTransaction _transaction;
    private readonly ITransactionalEmailSender _emailSender;
    private readonly ICriticalEmailAlerter _criticalAlerter;
    private readonly EmailOptions _emailOptions;

    public RegisterCommandHandler(
        UserManager<StoreUser> userManager,
        IAuditLogger auditLogger,
        IResilientTransaction transaction,
        ITransactionalEmailSender emailSender,
        ICriticalEmailAlerter criticalAlerter,
        IOptions<EmailOptions> emailOptions)
    {
        _userManager = userManager;
        _auditLogger = auditLogger;
        _transaction = transaction;
        _emailSender = emailSender;
        _criticalAlerter = criticalAlerter;
        _emailOptions = emailOptions.Value;
    }

    public async Task<Result<AuthResponseDto>> Handle(RegisterCommand request, CancellationToken cancellationToken)
    {
        var correlationId = request.HttpContext.GetCorrelationId();
        var ipAddress = request.HttpContext.GetClientIpAddress();
        var userAgent = request.HttpContext.GetUserAgent();

        // The introduction-exchange blocked a second account whose email NORMALIZED to an existing
        // one (dots and +tags stripped) — anti-Sybil, because there money moves between users and
        // one person wearing two faces is the attack. A storefront has no such incentive: accounts
        // buy, they do not transact with each other. What must hold here is narrower and stronger,
        // and the database holds it: AspNetUsers.NormalizedEmail is UNIQUE, so no two accounts can
        // claim the same address and be shown each other's orders. a+1@x.com and a@x.com are two
        // customers with two separate order histories, which is correct.

        var user = new StoreUser 
        { 
            UserName = request.Username, 
            Email = request.Email,
            TosVersionAccepted = request.TosVersion
        };

        string? createErrors = null;
        await _transaction.ExecuteAsync(async _ =>
        {
            var result = await _userManager.CreateAsync(user, request.Password).ConfigureAwait(false);
            if (!result.Succeeded)
            {
                createErrors = string.Join(", ", result.Errors.Select(e => e.Description));
                return false;
            }

            return true;
        }, cancellationToken).ConfigureAwait(false);

        // S2583 false positive, proven: Sonar's dataflow does not follow the delegate through
        // strategy.ExecuteAsync, so it concludes the lambda never runs and createErrors is still
        // null here. It does run — ResilientTransaction.cs:44 invokes it (`await operation(...)`),
        // and the runtime probe that validated the rollback fix printed "CreateAsync succeeded: True"
        // from inside this exact lambda. Suppressed, not restructured: the assignment-through-closure
        // is how a Task-returning ExecuteAsync reports why it rolled back.
#pragma warning disable S2583
        if (createErrors is not null)
#pragma warning restore S2583
        {
            return Result.Failure<AuthResponseDto>(new Error("Auth.RegistrationFailed", createErrors, ErrorType.Validation));
        }

        await _auditLogger.LogAsync(new AuditEvent
        {
            Action = AuditActions.Register,
            UserId = user.Id.ToString(),
            Resource = $"User:{user.Id}",
            IsSuccess = true,
            IpAddress = ipAddress,
            UserAgent = userAgent,
            CorrelationId = correlationId
        }, cancellationToken).ConfigureAwait(false);

        // Mint the email-verification token and send the verification email. Pure crypto + an
        // outbound send, both safe outside the create transaction. The frontend's "check your email"
        // interstitial pairs with the link, which lands on /verify-email and POSTs to
        // /v1/auth/verify-email {user_id, token}. The sender is non-throwing and no-ops to a log when
        // email is unconfigured (dev/test), so a delivery hiccup never fails an otherwise-good signup.
        var verificationToken = await _userManager.GenerateEmailConfirmationTokenAsync(user).ConfigureAwait(false);
        var verifyLink = EmailTemplates.VerificationLink(_emailOptions.WebBaseUrl, user.Id.ToString(), verificationToken);
        var (subject, html) = EmailTemplates.Verification(verifyLink);
        var delivered = await _emailSender.SendAsync(user.Email!, subject, html, cancellationToken).ConfigureAwait(false);
        if (!delivered.Accepted)
        {
            // D-84: a swallowed verification-send failure leaves a password-signup user unable to log in
            // (LoginCommand refuses EmailConfirmed=false) with no operator signal. Escalate loudly. PII-free:
            // the user id only, never the email address.
            await _criticalAlerter.RaiseSendFailureAsync($"registration email verification (user {user.Id})", cancellationToken).ConfigureAwait(false);
        }

        // Per E01-001/002: No JWT is issued until email is verified.
        return Result.Success(new AuthResponseDto
        {
            UserId = user.Id.ToString(),
            Username = user.UserName,
            Email = user.Email,
            Message = "Registration successful. Please verify your email."
        });
    }
}
