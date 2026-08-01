using MediatR;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using Store.Api.Common;
using Store.Catalog.Domain.Identity;
using Store.Catalog.Persistence;

namespace Store.Api.Identity;

public sealed record GetProfileQuery(Guid UserId) : IRequest<Result<UserAndProfileDto>>;

internal sealed class GetProfileQueryHandler : IRequestHandler<GetProfileQuery, Result<UserAndProfileDto>>
{
    private readonly UserManager<StoreUser> _userManager;
    private readonly StoreDbContext _db;

    public GetProfileQueryHandler(UserManager<StoreUser> userManager, StoreDbContext db)
    {
        _userManager = userManager;
        _db = db;
    }

    public async Task<Result<UserAndProfileDto>> Handle(GetProfileQuery request, CancellationToken cancellationToken)
    {
        var user = await _userManager.Users
            .AsNoTracking()
            .FirstOrDefaultAsync(u => u.Id == request.UserId, cancellationToken).ConfigureAwait(false);

        if (user == null)
            return Result.Failure<UserAndProfileDto>(Error.Auth.UserNotFound);

        var profile = await _db.UserProfiles
            .FirstOrDefaultAsync(p => p.UserId == request.UserId, cancellationToken).ConfigureAwait(false);

        if (profile == null)
        {
            // Lazy create profile
            profile = UserProfile.Create(request.UserId);
            _db.UserProfiles.Add(profile);
            await _db.SaveChangesAsync(cancellationToken).ConfigureAwait(false);
        }

        return Result.Success(new UserAndProfileDto
        {
            Id = user.Id,
            Email = user.Email ?? string.Empty,
            Username = user.UserName ?? string.Empty,
            EmailConfirmed = user.EmailConfirmed,
            TosVersionAccepted = user.TosVersionAccepted,
            CreatedAt = user.CreatedAt,
            Profile = new UserProfileDto
            {
                FirstName = profile.FirstName,
                LastName = profile.LastName,
                Phone = profile.Phone,
                Bio = profile.Bio,
                Website = profile.Website,
                AvatarUrl = profile.AvatarUrl,
                Country = profile.Country
            }
        });
    }
}
