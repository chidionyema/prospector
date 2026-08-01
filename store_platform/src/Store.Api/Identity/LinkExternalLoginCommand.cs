using MediatR;
using Microsoft.AspNetCore.Identity;
using Microsoft.Extensions.Logging;
using Store.Catalog.Domain.Identity;
using Store.Api.Common;

namespace Store.Api.Identity;

/// <summary>
/// Links a newly-authorised provider to the CURRENT (already authenticated) user — the Settings
/// "connect account" round-trip (E16). Rejects a provider key already bound to a different TIE user
/// (§0.4: explicit-link of an already-bound key → reject), preventing account takeover by linking.
/// </summary>
public sealed record LinkExternalLoginCommand(Guid UserId) : IRequest<Result<bool>>;

internal sealed class LinkExternalLoginCommandHandler : IRequestHandler<LinkExternalLoginCommand, Result<bool>>
{
    private readonly SignInManager<StoreUser> _signInManager;
    private readonly UserManager<StoreUser> _userManager;
    private readonly ILogger<LinkExternalLoginCommandHandler> _logger;

    public LinkExternalLoginCommandHandler(
        SignInManager<StoreUser> signInManager,
        UserManager<StoreUser> userManager,
        ILogger<LinkExternalLoginCommandHandler> logger)
    {
        _signInManager = signInManager;
        _userManager = userManager;
        _logger = logger;
    }

    public async Task<Result<bool>> Handle(LinkExternalLoginCommand request, CancellationToken cancellationToken)
    {
        var user = await _userManager.FindByIdAsync(request.UserId.ToString()).ConfigureAwait(false);
        if (user is null)
            return Result.Failure<bool>(Error.Auth.UserNotFound);

        var loginInfo = await _signInManager.GetExternalLoginInfoAsync().ConfigureAwait(false);
        if (loginInfo is null || string.IsNullOrWhiteSpace(loginInfo.ProviderKey))
            return Result.Failure<bool>(Error.Auth.ExternalLoginFailed);

        // Reject if this provider key is already bound — to this or any other user.
        var owner = await _userManager.FindByLoginAsync(loginInfo.LoginProvider, loginInfo.ProviderKey).ConfigureAwait(false);
        if (owner is not null)
        {
            if (owner.Id == user.Id) return Result.Success(true); // idempotent: already linked to me
            _logger.LogWarning("Refusing to link {Provider}: key already bound to user {OwnerId}.",
                loginInfo.LoginProvider, owner.Id);
            return Result.Failure<bool>(Error.Auth.AlreadyLinked);
        }

        var result = await _userManager.AddLoginAsync(user, loginInfo).ConfigureAwait(false);
        if (!result.Succeeded)
        {
            _logger.LogWarning("Link {Provider} to {UserId} failed: {Errors}", loginInfo.LoginProvider,
                user.Id, string.Join(", ", result.Errors.Select(e => e.Description)));
            return Result.Failure<bool>(Error.Auth.LinkFailed);
        }

        _logger.LogInformation("Linked {Provider} to user {UserId}.", loginInfo.LoginProvider, user.Id);
        return Result.Success(true);
    }
}
