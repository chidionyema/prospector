using MediatR;
using Microsoft.EntityFrameworkCore;
using Store.Api.Common;
using Store.Api.Common.Audit;
using Store.Catalog.Persistence;

namespace Store.Api.Identity;

public sealed record RevokeSessionCommand(Guid UserId, Guid FamilyId) : IRequest<Result>;

internal sealed class RevokeSessionCommandHandler : IRequestHandler<RevokeSessionCommand, Result>
{
    private readonly StoreDbContext _db;
    private readonly IAuditLogger _auditLogger;
    private readonly ITokenRevocationService _revocationService;

    public RevokeSessionCommandHandler(
        StoreDbContext db, 
        IAuditLogger auditLogger,
        ITokenRevocationService revocationService)
    {
        _db = db;
        _auditLogger = auditLogger;
        _revocationService = revocationService;
    }

    public async Task<Result> Handle(RevokeSessionCommand request, CancellationToken cancellationToken)
    {
        // 1. Find all tokens in the family to revoke their access JTIs
        var tokens = await _db.RefreshTokens
            .Where(rt => rt.UserId == request.UserId && rt.FamilyId == request.FamilyId && !rt.IsRevoked)
            .ToListAsync(cancellationToken).ConfigureAwait(false);

        if (tokens.Count == 0)
            return Result.Failure(Error.NotFound("Auth.SessionNotFound", "Session not found or already revoked."));

        // 2. Revoke each access token JTI
        foreach (var token in tokens.Where(t => !string.IsNullOrEmpty(t.AccessTokenJti)))
        {
            // We don't have the exact expiry of the access token here, but we know it's short-lived (15m).
            // Revoking it for 1 hour is safe.
            await _revocationService.RevokeTokenAsync(token.AccessTokenJti!, request.UserId.ToString(), DateTime.UtcNow.AddHours(1), cancellationToken).ConfigureAwait(false);
        }

        // 3. Revoke the refresh token family
        foreach (var token in tokens)
        {
            token.Revoke();
        }

        await _db.SaveChangesAsync(cancellationToken).ConfigureAwait(false);

        await _auditLogger.LogAsync(new AuditEvent
        {
            Action = AuditActions.Logout,
            UserId = request.UserId.ToString(),
            Resource = $"SessionFamily:{request.FamilyId}",
            IsSuccess = true,
            Details = "Session family and associated access tokens revoked by user"
        }, cancellationToken).ConfigureAwait(false);

        return Result.Success();
    }
}
