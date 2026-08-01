using MediatR;
using Microsoft.EntityFrameworkCore;
using Store.Api.Common;
using Store.Catalog.Persistence;

namespace Store.Api.Identity;

public sealed record ListSessionsQuery(Guid UserId, string? CurrentRefreshToken = null) : IRequest<Result<List<SessionDto>>>;

internal sealed class ListSessionsQueryHandler : IRequestHandler<ListSessionsQuery, Result<List<SessionDto>>>
{
    private readonly StoreDbContext _db;

    public ListSessionsQueryHandler(StoreDbContext db)
    {
        _db = db;
    }

    public async Task<Result<List<SessionDto>>> Handle(ListSessionsQuery request, CancellationToken cancellationToken)
    {
        // Get the latest active token for each family.
        var sessions = await _db.RefreshTokens
            .Where(rt => rt.UserId == request.UserId && !rt.IsRevoked && rt.Expires > DateTime.UtcNow)
            .GroupBy(rt => rt.FamilyId)
            .Select(g => g.OrderByDescending(rt => rt.CreatedAt).First())
            .ToListAsync(cancellationToken).ConfigureAwait(false);

        var dtos = sessions.Select(s => new SessionDto
        {
            FamilyId = s.FamilyId,
            UserAgent = s.CreatedUserAgent,
            IpAddress = s.CreatedFromIp,
            CreatedAt = s.CreatedAt,
            Expires = s.Expires,
            IsCurrent = request.CurrentRefreshToken != null && string.Equals(s.Token, request.CurrentRefreshToken, StringComparison.Ordinal)
        }).OrderByDescending(s => s.CreatedAt).ToList();

        return Result.Success(dtos);
    }
}
