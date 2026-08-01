using System.Text.Json.Serialization;
using MediatR;
using Microsoft.AspNetCore.Identity;
using Store.Catalog.Domain.Identity;
using Store.Api.Common;

namespace Store.Api.Identity;

/// <summary>The providers currently linked to a user, plus whether they also have a password — drives
/// the Settings "Connected accounts" panel and the unlink-last-credential guard in the UI (E16).</summary>
public sealed class UserLoginsDto
{
    [JsonPropertyName("providers")] public IReadOnlyList<string> Providers { get; set; } = [];
    [JsonPropertyName("has_password")] public bool HasPassword { get; set; }
}

public sealed record GetUserLoginsQuery(Guid UserId) : IRequest<Result<UserLoginsDto>>;

internal sealed class GetUserLoginsQueryHandler : IRequestHandler<GetUserLoginsQuery, Result<UserLoginsDto>>
{
    private readonly UserManager<StoreUser> _userManager;

    public GetUserLoginsQueryHandler(UserManager<StoreUser> userManager) => _userManager = userManager;

    public async Task<Result<UserLoginsDto>> Handle(GetUserLoginsQuery request, CancellationToken cancellationToken)
    {
        var user = await _userManager.FindByIdAsync(request.UserId.ToString()).ConfigureAwait(false);
        if (user is null)
            return Result.Failure<UserLoginsDto>(Error.Auth.UserNotFound);

        var logins = await _userManager.GetLoginsAsync(user).ConfigureAwait(false);
        return Result.Success(new UserLoginsDto
        {
            Providers = logins.Select(l => l.LoginProvider).OrderBy(p => p, StringComparer.Ordinal).ToList(),
            HasPassword = await _userManager.HasPasswordAsync(user)
        .ConfigureAwait(false)});
    }
}
