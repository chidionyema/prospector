using System.Security.Claims;
using System.Text.Json.Serialization;
using MediatR;
using Microsoft.AspNetCore.Mvc;
using Store.Api.Identity;
using Store.Api.Common;

namespace Store.Api.Auth;

public class RegisterRequest
{
    public RegisterRequest() { }
    public RegisterRequest(string username, string email, string password, string? role, string? tosVersion)
    {
        Username = username;
        Email = email;
        Password = password;
        Role = role;
        TosVersion = tosVersion;
    }

    [JsonPropertyName("username")] public string Username { get; set; } = string.Empty;
    [JsonPropertyName("email")] public string Email { get; set; } = string.Empty;
    [JsonPropertyName("password")] public string Password { get; set; } = string.Empty;
    // Optional: the role pick moved to /auth/choose-role on first login (role-less registration).
    [JsonPropertyName("role")] public string? Role { get; set; }
    [JsonPropertyName("tos_version")] public string? TosVersion { get; set; }
}

public class LoginRequest
{
    public LoginRequest() { }
    public LoginRequest(string username, string password)
    {
        Username = username;
        Password = password;
    }

    [JsonPropertyName("username")] public string Username { get; set; } = string.Empty;
    [JsonPropertyName("password")] public string Password { get; set; } = string.Empty;
}

public class RefreshRequest
{
    public RefreshRequest() { }
    public RefreshRequest(string accessToken, string refreshToken)
    {
        AccessToken = accessToken;
        RefreshToken = refreshToken;
    }

    [JsonPropertyName("access_token")] public string AccessToken { get; set; } = string.Empty;
    [JsonPropertyName("refresh_token")] public string RefreshToken { get; set; } = string.Empty;
}

/// <summary>
/// Body of PUT /v1/auth/me. Every field is nullable and maps to empty rather than being required:
/// this is a full replace, so a client that omits a field means "clear it", and a client that sends
/// the whole object round-trips GET /v1/auth/me unchanged. There is deliberately no UserId — see
/// the endpoint.
/// </summary>
public class UpdateProfileRequest
{
    [JsonPropertyName("first_name")] public string? FirstName { get; set; }
    [JsonPropertyName("last_name")] public string? LastName { get; set; }
    [JsonPropertyName("phone")] public string? Phone { get; set; }
    [JsonPropertyName("bio")] public string? Bio { get; set; }
    [JsonPropertyName("website")] public string? Website { get; set; }
    [JsonPropertyName("avatar_url")] public string? AvatarUrl { get; set; }
    [JsonPropertyName("country")] public string? Country { get; set; }
}

public class ChangePasswordRequest
{
    public ChangePasswordRequest() { }
    public ChangePasswordRequest(string currentPassword, string newPassword)
    {
        CurrentPassword = currentPassword;
        NewPassword = newPassword;
    }

    [JsonPropertyName("current_password")] public string CurrentPassword { get; set; } = string.Empty;
    [JsonPropertyName("new_password")] public string NewPassword { get; set; } = string.Empty;
}

public class ForgotPasswordRequest
{
    public ForgotPasswordRequest() { }
    public ForgotPasswordRequest(string email) { Email = email; }

    [JsonPropertyName("email")] public string Email { get; set; } = string.Empty;
}

public class ResetPasswordRequest
{
    public ResetPasswordRequest() { }
    public ResetPasswordRequest(string email, string token, string newPassword)
    {
        Email = email;
        Token = token;
        NewPassword = newPassword;
    }

    [JsonPropertyName("email")] public string Email { get; set; } = string.Empty;
    [JsonPropertyName("token")] public string Token { get; set; } = string.Empty;
    [JsonPropertyName("new_password")] public string NewPassword { get; set; } = string.Empty;
}

public class VerifyEmailRequest
{
    public VerifyEmailRequest() { }
    public VerifyEmailRequest(string userId, string token)
    {
        UserId = userId;
        Token = token;
    }

    [JsonPropertyName("user_id")] public string UserId { get; set; } = string.Empty;
    [JsonPropertyName("token")] public string Token { get; set; } = string.Empty;
}

public class ResendVerificationRequest
{
    public ResendVerificationRequest() { }
    public ResendVerificationRequest(string email) { Email = email; }

    [JsonPropertyName("email")] public string Email { get; set; } = string.Empty;
}

/// <summary>
/// Auth HTTP surface (minimal API), dispatching the ported haworks MediatR
/// commands. register / login / logout / refresh / me — JWT bearer, no Vault.
/// The injected <see cref="CancellationToken"/> binds to HttpContext.RequestAborted
/// and flows through MediatR into the handlers' EF/identity calls.
/// </summary>
public static class AuthEndpoints
{
    public static void MapAuthEndpoints(this IEndpointRouteBuilder app)
    {
        var auth = app.MapGroup("/v1/auth");

        auth.MapPost("/register", async ([FromBody] RegisterRequest req, IMediator mediator, HttpContext ctx, CancellationToken ct) =>
        {
            var result = await mediator.Send(new RegisterCommand(req.Username, req.Email, req.Password, req.TosVersion, ctx), ct).ConfigureAwait(false);
            return result.IsSuccess ? Results.Ok(result.Value) : result.Error.ToHttp();
        });

        auth.MapPost("/login", async ([FromBody] LoginRequest req, IMediator mediator, HttpContext ctx, CancellationToken ct) =>
        {
            var result = await mediator.Send(new LoginCommand(req.Username, req.Password, ctx), ct).ConfigureAwait(false);
            return result.IsSuccess ? Results.Ok(result.Value) : result.Error.ToHttp();
        }).Produces<AuthResponseDto>(StatusCodes.Status200OK);

        auth.MapPost("/forgot-password", async ([FromBody] ForgotPasswordRequest req, IMediator mediator, CancellationToken ct) =>
        {
            var result = await mediator.Send(new ForgotPasswordCommand(req.Email), ct).ConfigureAwait(false);
            return result.IsSuccess ? Results.Ok(new { message = "If an account with that email exists, a reset link has been sent." }) : result.Error.ToHttp();
        });

        auth.MapPost("/reset-password", async ([FromBody] ResetPasswordRequest req, IMediator mediator, CancellationToken ct) =>
        {
            var result = await mediator.Send(new ResetPasswordCommand(req.Email, req.Token, req.NewPassword), ct).ConfigureAwait(false);
            return result.IsSuccess ? Results.Ok(new { message = "Password reset successful" }) : result.Error.ToHttp();
        });

        // Email verification. Anti-enumeration: a bad user id or a bad token both yield the same
        // generic 400, so the response never reveals which accounts exist. Verifying an already
        // verified account is idempotent and returns 200. Under the global "/v1/auth" rate limiter.
        auth.MapPost("/verify-email", async ([FromBody] VerifyEmailRequest req, IMediator mediator, CancellationToken ct) =>
        {
            var result = await mediator.Send(new VerifyEmailCommand(req.UserId, req.Token), ct).ConfigureAwait(false);
            return result.IsSuccess ? Results.Ok(new { message = "Email verified. You can now log in." }) : result.Error.ToHttp();
        });

        // Re-issue a verification token. Always 200 (enumeration-safe), rate-limited via /v1/auth.
        auth.MapPost("/resend-verification", async ([FromBody] ResendVerificationRequest req, IMediator mediator, CancellationToken ct) =>
        {
            var result = await mediator.Send(new ResendVerificationCommand(req.Email), ct).ConfigureAwait(false);
            return result.IsSuccess ? Results.Ok(new { message = "If your email is registered and unverified, a new verification link has been sent." }) : result.Error.ToHttp();
        });

        auth.MapPost("/refresh", async ([FromBody] RefreshRequest req, IMediator mediator, HttpContext ctx, CancellationToken ct) =>
        {
            var result = await mediator.Send(new RefreshTokenCommand(req.AccessToken, req.RefreshToken, ctx), ct).ConfigureAwait(false);
            return result.IsSuccess ? Results.Ok(result.Value) : result.Error.ToHttp();
        });

        auth.MapPost("/logout", async (IMediator mediator, HttpContext ctx, ClaimsPrincipal user, CancellationToken ct) =>
        {
            var result = await mediator.Send(new LogoutCommand(user, ctx), ct).ConfigureAwait(false);
            return result.IsSuccess ? Results.Ok(new { message = "Logged out" }) : result.Error.ToHttp();
        }).RequireAuthorization();

        auth.MapGet("/me", async (IMediator mediator, ClaimsPrincipal user, CancellationToken ct) =>
        {
            var result = await mediator.Send(new GetProfileQuery(user.UserId()), ct).ConfigureAwait(false);
            return result.IsSuccess ? Results.Ok(result.Value) : result.Error.ToHttp();
        }).RequireAuthorization();

        // Full-replace edit of the caller's own profile. The user id comes from the JWT, never the
        // body — a UserId field here would let any authenticated customer rewrite another's profile.
        auth.MapPut("/me", async ([FromBody] UpdateProfileRequest req, IMediator mediator, ClaimsPrincipal user, CancellationToken ct) =>
        {
            var result = await mediator.Send(
                new UpdateProfileCommand(
                    user.UserId(),
                    req.FirstName ?? string.Empty,
                    req.LastName ?? string.Empty,
                    req.Phone ?? string.Empty,
                    req.Bio ?? string.Empty,
                    req.Website ?? string.Empty,
                    req.AvatarUrl ?? string.Empty,
                    req.Country ?? string.Empty),
                ct).ConfigureAwait(false);
            return result.IsSuccess ? Results.Ok(result.Value) : result.Error.ToHttp();
        }).RequireAuthorization();

        auth.MapPost("/change-password", async ([FromBody] ChangePasswordRequest req, IMediator mediator, ClaimsPrincipal user, CancellationToken ct) =>
        {
            var result = await mediator.Send(new ChangePasswordCommand(user.UserId(), req.CurrentPassword, req.NewPassword), ct).ConfigureAwait(false);
            return result.IsSuccess ? Results.Ok(new { message = "Password changed successfully" }) : result.Error.ToHttp();
        }).RequireAuthorization();

        auth.MapGet("/sessions", async (IMediator mediator, ClaimsPrincipal user, CancellationToken ct) =>
        {
            // Note: In a real app we'd pass the current refresh token from cookie to mark 'IsCurrent'
            var result = await mediator.Send(new ListSessionsQuery(user.UserId()), ct).ConfigureAwait(false);
            return result.IsSuccess ? Results.Ok(result.Value) : result.Error.ToHttp();
        }).RequireAuthorization();

        auth.MapDelete("/sessions/{familyId:guid}", async (Guid familyId, IMediator mediator, ClaimsPrincipal user, CancellationToken ct) =>
        {
            var result = await mediator.Send(new RevokeSessionCommand(user.UserId(), familyId), ct).ConfigureAwait(false);
            return result.IsSuccess ? Results.NoContent() : result.Error.ToHttp();
        }).RequireAuthorization();
    }

    public static IResult ToHttp(this Error error) 
    {
        return error.Type switch
        {
            ErrorType.Validation => Results.BadRequest(new { error = error.Message, code = error.Code }),
            ErrorType.Unauthorized => Results.Json(new { error = error.Message, code = error.Code }, statusCode: 401),
            ErrorType.Forbidden => Results.Json(new { error = error.Message, code = error.Code }, statusCode: 403),
            ErrorType.NotFound => Results.NotFound(new { error = error.Message, code = error.Code }),
            ErrorType.Conflict => Results.Conflict(new { error = error.Message, code = error.Code }),
            _ => Results.Json(new { error = error.Message, code = error.Code }, statusCode: 500)
        };
    }
}
