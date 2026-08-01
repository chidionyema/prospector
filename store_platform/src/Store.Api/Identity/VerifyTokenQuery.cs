using System.Security.Claims;
using MediatR;
using Store.Api.Common;

namespace Store.Api.Identity;

public sealed record VerifyTokenQuery(ClaimsPrincipal User) : IRequest<Result<TokenVerificationDto>>;

internal sealed class VerifyTokenQueryHandler : IRequestHandler<VerifyTokenQuery, Result<TokenVerificationDto>>
{
    public Task<Result<TokenVerificationDto>> Handle(VerifyTokenQuery request, CancellationToken cancellationToken)
    {
        var userId = request.User.FindFirstValue(ClaimTypes.NameIdentifier) ?? request.User.FindFirstValue("sub");
        if (string.IsNullOrEmpty(userId))
            return Task.FromResult(Result.Failure<TokenVerificationDto>(Error.Auth.MissingUserId));

        return Task.FromResult(Result.Success(new TokenVerificationDto
        {
            UserId = userId,
            UserName = request.User.FindFirstValue(ClaimTypes.Name),
            IsAuthenticated = true,
            Message = "Token is valid"
        }));
    }
}
