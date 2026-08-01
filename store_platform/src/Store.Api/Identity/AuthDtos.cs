using System.Text.Json.Serialization;

namespace Store.Api.Identity;

/// <summary>Auth response payload. Ported from haworks Identity.Application/DTOs/AuthDtos.cs.</summary>
public sealed class AuthResponseDto
{
    [JsonPropertyName("token")] public string Token { get; set; } = string.Empty;
    [JsonPropertyName("refresh_token")] public string? RefreshToken { get; set; }
    [JsonPropertyName("user_id")] public string UserId { get; set; } = string.Empty;
    [JsonPropertyName("username")] public string? Username { get; set; }
    [JsonPropertyName("email")] public string? Email { get; set; }
    [JsonPropertyName("expires")] public DateTime Expires { get; set; }
    [JsonPropertyName("message")] public string? Message { get; set; }
}

public sealed class TokenVerificationDto
{
    [JsonPropertyName("user_id")] public string UserId { get; set; } = string.Empty;
    [JsonPropertyName("username")] public string? UserName { get; set; }
    [JsonPropertyName("is_authenticated")] public bool IsAuthenticated { get; set; }
    [JsonPropertyName("message")] public string? Message { get; set; }
}

public sealed class UserProfileDto
{
    [JsonPropertyName("first_name")] public string FirstName { get; set; } = string.Empty;
    [JsonPropertyName("last_name")] public string LastName { get; set; } = string.Empty;
    [JsonPropertyName("display_name")] public string DisplayName => $"{FirstName} {LastName}".Trim();
    [JsonPropertyName("phone")] public string Phone { get; set; } = string.Empty;
    [JsonPropertyName("bio")] public string Bio { get; set; } = string.Empty;
    [JsonPropertyName("website")] public string Website { get; set; } = string.Empty;
    [JsonPropertyName("avatar_url")] public string AvatarUrl { get; set; } = string.Empty;
    [JsonPropertyName("country")] public string Country { get; set; } = "GB";
}

public sealed class UserAndProfileDto
{
    [JsonPropertyName("id")] public Guid Id { get; set; }
    [JsonPropertyName("email")] public string Email { get; set; } = string.Empty;
    [JsonPropertyName("username")] public string Username { get; set; } = string.Empty;
    /// <summary>
    /// The introduction-exchange returned VerificationTier / StripeAccountId / PayoutReady here —
    /// all Connector-payout concerns a storefront has none of. Replaced by the three facts the
    /// store's account page actually needs.
    /// </summary>
    /// <remarks>
    /// <c>EmailConfirmed</c> is the important one: it is what gates order history, because orders
    /// are joined to an account by email string alone. The frontend renders the order list only
    /// when it is true, so an unverified account claiming someone else's address sees nothing.
    /// </remarks>
    [JsonPropertyName("email_confirmed")] public bool EmailConfirmed { get; set; }
    [JsonPropertyName("tos_version_accepted")] public string? TosVersionAccepted { get; set; }
    [JsonPropertyName("created_at")] public DateTime CreatedAt { get; set; }
    [JsonPropertyName("profile")] public UserProfileDto Profile { get; set; } = new();
}

public sealed class SessionDto
{
    [JsonPropertyName("family_id")] public Guid FamilyId { get; set; }
    [JsonPropertyName("user_agent")] public string? UserAgent { get; set; }
    [JsonPropertyName("ip_address")] public string? IpAddress { get; set; }
    [JsonPropertyName("created_at")] public DateTime CreatedAt { get; set; }
    [JsonPropertyName("expires")] public DateTime Expires { get; set; }
    [JsonPropertyName("is_current")] public bool IsCurrent { get; set; }
}
