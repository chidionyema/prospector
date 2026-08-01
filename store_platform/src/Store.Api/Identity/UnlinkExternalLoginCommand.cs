using MediatR;
using Microsoft.AspNetCore.Identity;
using Microsoft.Extensions.Logging;
using Store.Catalog.Domain.Identity;
using Store.Api.Common;

namespace Store.Api.Identity;

/// <summary>
/// Removes a linked provider from the current user (Settings, E16). Fails closed if it would strip
/// the user's ONLY remaining sign-in method (§0.4: unlink-last-credential → block) — a social-only
/// user with no password and one provider cannot lock themselves out. Set-password is post-beta.
/// </summary>
public sealed record UnlinkExternalLoginCommand(Guid UserId, string Provider) : IRequest<Result<bool>>;

internal sealed class UnlinkExternalLoginCommandHandler : IRequestHandler<UnlinkExternalLoginCommand, Result<bool>>
{
    private readonly UserManager<StoreUser> _userManager;
    private readonly ILogger<UnlinkExternalLoginCommandHandler> _logger;

    public UnlinkExternalLoginCommandHandler(
        UserManager<StoreUser> userManager,
        ILogger<UnlinkExternalLoginCommandHandler> logger)
    {
        _userManager = userManager;
        _logger = logger;
    }

    public async Task<Result<bool>> Handle(UnlinkExternalLoginCommand request, CancellationToken cancellationToken)
    {
        var user = await _userManager.FindByIdAsync(request.UserId.ToString()).ConfigureAwait(false);
        if (user is null)
            return Result.Failure<bool>(Error.Auth.UserNotFound);

        var logins = await _userManager.GetLoginsAsync(user).ConfigureAwait(false);
        var target = logins.FirstOrDefault(l =>
            string.Equals(l.LoginProvider, request.Provider, StringComparison.OrdinalIgnoreCase));
        if (target is null)
            return Result.Failure<bool>(Error.Auth.LoginNotFound);

        // Last-credential guard: removing this provider is only safe if the user keeps another way in
        // (a password, or at least one other linked provider).
        var hasPassword = await _userManager.HasPasswordAsync(user).ConfigureAwait(false);
        var otherLogins = logins.Count - 1;
        if (!hasPassword && otherLogins == 0)
        {
            _logger.LogWarning("Refusing to unlink last credential ({Provider}) for user {UserId}.",
                request.Provider, user.Id);
            return Result.Failure<bool>(new Error(
                "Auth.LastCredential", "You can't remove your only sign-in method.", ErrorType.Conflict));
        }

        var result = await _userManager.RemoveLoginAsync(user, target.LoginProvider, target.ProviderKey).ConfigureAwait(false);
        if (!result.Succeeded)
        {
            _logger.LogWarning("Unlink {Provider} for {UserId} failed: {Errors}", request.Provider,
                user.Id, string.Join(", ", result.Errors.Select(e => e.Description)));
            return Result.Failure<bool>(Error.Auth.UnlinkFailed);
        }

        _logger.LogInformation("Unlinked {Provider} from user {UserId}.", request.Provider, user.Id);
        return Result.Success(true);
    }
}
