using FluentValidation;
using MediatR;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using Store.Api.Common;
using Store.Catalog.Domain.Identity;
using Store.Api.Common.Audit;
using Store.Catalog.Persistence;

namespace Store.Api.Identity;

/// <summary>Full-replace edit of the caller's own profile (PUT /v1/me semantics). Email and
/// username are out of scope here — they have their own (re-verified) flows. Avatar/website are
/// validated as absolute http(s) URLs and stored verbatim; the server never fetches them (no SSRF).</summary>
public sealed record UpdateProfileCommand(
    Guid UserId,
    string FirstName,
    string LastName,
    string Phone,
    string Bio,
    string Website,
    string AvatarUrl,
    string Country) : IRequest<Result<UserAndProfileDto>>;

public sealed class UpdateProfileCommandValidator : AbstractValidator<UpdateProfileCommand>
{
    public UpdateProfileCommandValidator()
    {
        RuleFor(x => x.FirstName).MaximumLength(100);
        RuleFor(x => x.LastName).MaximumLength(100);
        RuleFor(x => x.Phone).MaximumLength(30);
        RuleFor(x => x.Bio).MaximumLength(2000);

        RuleFor(x => x.Website)
            .Must(BeAbsoluteHttpUrl)
            .WithMessage("Website must be an absolute http(s) URL.")
            .When(x => !string.IsNullOrWhiteSpace(x.Website));

        RuleFor(x => x.AvatarUrl)
            .Must(BeAbsoluteHttpUrl)
            .WithMessage("Avatar URL must be an absolute http(s) URL.")
            .When(x => !string.IsNullOrWhiteSpace(x.AvatarUrl));

        RuleFor(x => x.Country)
            .Must(IsoCountries.IsValid)
            .WithMessage("Country must be a valid ISO-3166-1 alpha-2 code.")
            .When(x => !string.IsNullOrWhiteSpace(x.Country));
    }

    // Only absolute http/https URLs — rejects relative paths and dangerous schemes (javascript:, data:, file:).
    private static bool BeAbsoluteHttpUrl(string url) =>
        Uri.TryCreate(url, UriKind.Absolute, out var uri) &&
        (string.Equals(uri.Scheme, Uri.UriSchemeHttp, StringComparison.Ordinal) ||
         string.Equals(uri.Scheme, Uri.UriSchemeHttps, StringComparison.Ordinal));
}

internal sealed class UpdateProfileCommandHandler : IRequestHandler<UpdateProfileCommand, Result<UserAndProfileDto>>
{
    private readonly UserManager<StoreUser> _userManager;
    private readonly StoreDbContext _db;
    private readonly IAuditLogger _auditLogger;

    public UpdateProfileCommandHandler(UserManager<StoreUser> userManager, StoreDbContext db, IAuditLogger auditLogger)
    {
        _userManager = userManager;
        _db = db;
        _auditLogger = auditLogger;
    }

    public async Task<Result<UserAndProfileDto>> Handle(UpdateProfileCommand request, CancellationToken cancellationToken)
    {
        var user = await _userManager.Users
            .AsNoTracking()
            .FirstOrDefaultAsync(u => u.Id == request.UserId, cancellationToken).ConfigureAwait(false);

        if (user is null)
            return Result.Failure<UserAndProfileDto>(Error.Auth.UserNotFound);

        if (!user.IsActive)
            return Result.Failure<UserAndProfileDto>(Error.Auth.AccountDeactivated);

        // Upsert: lazy-create the profile row if this user has never had one (matches GetProfileQuery).
        var profile = await _db.UserProfiles
            .FirstOrDefaultAsync(p => p.UserId == request.UserId, cancellationToken).ConfigureAwait(false);
        if (profile is null)
        {
            profile = UserProfile.Create(request.UserId);
            _db.UserProfiles.Add(profile);
        }

        var country = string.IsNullOrWhiteSpace(request.Country) ? "GB" : request.Country.ToUpperInvariant();
        profile.Edit(
            request.FirstName,
            request.LastName,
            request.Phone,
            request.Bio,
            request.Website,
            request.AvatarUrl,
            country);

        try
        {
            await _db.SaveChangesAsync(cancellationToken).ConfigureAwait(false);
        }
        catch (DbUpdateConcurrencyException)
        {
            // No row-version token exists on SQLite (see AuditableEntity on why xmin was not
            // ported), so this fires only on a genuine constraint clash — the unique
            // UserProfile.UserId index when two lazy-creates race. Re-read and retry.
            return Result.Failure<UserAndProfileDto>(
                new Error("Profile.Concurrency", "Profile was modified concurrently. Please retry.", ErrorType.Conflict));
        }

        await _auditLogger.LogAsync(new AuditEvent
        {
            Action = AuditActions.ProfileUpdate,
            UserId = user.Id.ToString(),
            Resource = $"User:{user.Id}",
            IsSuccess = true,
            Details = "Profile updated"
        }, cancellationToken).ConfigureAwait(false);

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
