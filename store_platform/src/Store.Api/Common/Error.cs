namespace Store.Api.Common;

/// <summary>
/// Categorizes the type of error for HTTP status code mapping (done in the API layer).
/// Ported from haworks-platform BuildingBlocks/Common/Error.cs, trimmed to TIE's domain.
/// </summary>
public enum ErrorType
{
    None,
    Validation,
    NotFound,
    Conflict,
    Forbidden,
    Timeout,
    Internal,
    Unauthorized,
    Failure
}

/// <summary>
/// A type-safe error with a code, message, and category. Used throughout the
/// application instead of stringly-typed exceptions for expected failures.
/// </summary>
public sealed record Error(string Code, string Message, ErrorType Type = ErrorType.Internal)
{
    public static readonly Error None = new(string.Empty, string.Empty, ErrorType.None);

    public static Error Validation(string code, string message) => new(code, message, ErrorType.Validation);
    public static Error NotFound(string code, string message) => new(code, message, ErrorType.NotFound);
    public static Error Conflict(string code, string message) => new(code, message, ErrorType.Conflict);
    public static Error Forbidden(string code, string message) => new(code, message, ErrorType.Forbidden);
    public static Error Unauthorized(string code, string message) => new(code, message, ErrorType.Unauthorized);
    public static Error Timeout(string code, string message) => new(code, message, ErrorType.Timeout);
    public static Error Internal(string code, string message) => new(code, message, ErrorType.Internal);

    /// <summary>Auth error catalog, ported from haworks BuildingBlocks/Common/Error.Auth.</summary>
    public static class Auth
    {
        public static readonly Error InvalidCredentials = new("Auth.InvalidCredentials", "Invalid username or password", ErrorType.Unauthorized);
        public static readonly Error TokenExpired = new("Auth.TokenExpired", "Token has expired", ErrorType.Unauthorized);
        public static readonly Error TokenRevoked = new("Auth.TokenRevoked", "Token has been revoked", ErrorType.Unauthorized);
        // A generic `Auth.Unauthorized` is not ported. It shadowed the outer Error.Unauthorized(code,
        // message) factory (S3218), so `Error.Unauthorized` meant the field here in some scopes and
        // the factory in others — and nothing referenced it, because every call site names the
        // specific reason (InvalidCredentials, UnverifiedEmail, TokenRevoked ...). A caller-facing
        // auth failure should say which one it was.
        public static readonly Error UserNotFound = new("Auth.UserNotFound", "StoreUser not found", ErrorType.Unauthorized);
        public static readonly Error MissingTokens = new("Auth.MissingTokens", "Access and refresh tokens are required.", ErrorType.Validation);
        public static readonly Error InvalidAccessToken = new("Auth.InvalidAccessToken", "Invalid access token structure.", ErrorType.Unauthorized);
        public static readonly Error MissingUserId = new("Auth.MissingUserId", "Token claims are missing user identification.", ErrorType.Unauthorized);
        public static readonly Error InvalidRefreshToken = new("Auth.InvalidRefreshToken", "Session invalid. Please log in again.", ErrorType.Unauthorized);
        public static readonly Error TokenProcessingError = new("Auth.TokenProcessingError", "Invalid token signature.", ErrorType.Unauthorized);
        public static readonly Error RefreshFailed = new("Auth.RefreshFailed", "An internal error occurred.", ErrorType.Internal);
        public static readonly Error LoginNotFound = new("Auth.LoginNotFound", "External login not found.", ErrorType.Validation);
        public static readonly Error LinkFailed = new("Auth.LinkFailed", "Unable to link external login.", ErrorType.Internal);
        public static readonly Error UnlinkFailed = new("Auth.UnlinkFailed", "Unable to unlink external login.", ErrorType.Internal);
        public static readonly Error RegistrationFailed = new("Auth.RegistrationFailed", "Registration failed.", ErrorType.Validation);
        public static readonly Error RoleAssignmentFailed = new("Auth.RoleAssignmentFailed", "Role assignment failed.", ErrorType.Internal);
        public static readonly Error ClaimAssignmentFailed = new("Auth.ClaimAssignmentFailed", "Claim assignment failed.", ErrorType.Internal);
        public static readonly Error InvalidProviderKey = new("Auth.InvalidProviderKey", "External login information is incomplete.", ErrorType.Validation);
        public static readonly Error InvalidContext = new("Auth.InvalidContext", "HTTP context is required.", ErrorType.Validation);
        public static readonly Error ExternalLoginFailed = new("Auth.ExternalLoginFailed", "Unable to retrieve external login information.", ErrorType.Validation);
        public static readonly Error MissingEmail = new("Auth.MissingEmail", "Email is required but not provided by the external login.", ErrorType.Validation);
        public static readonly Error UnverifiedEmail = new("Auth.UnverifiedEmail", "Email must be verified by the external provider before linking accounts.", ErrorType.Validation);
        public static readonly Error AlreadyLinked = new("Auth.AlreadyLinked", "This external account is already connected to another user.", ErrorType.Conflict);
        public static readonly Error UserInconsistency = new("Auth.UserInconsistency", "Account inconsistency detected.", ErrorType.Internal);
        public static readonly Error CreateFailed = new("Auth.CreateFailed", "Could not create a new account.", ErrorType.Internal);
        public static readonly Error AccountDeactivated = new("Auth.AccountDeactivated", "Account is deactivated.", ErrorType.Forbidden);

        public static Error AccountLocked(int lockoutMinutes) =>
            new("Auth.AccountLocked", $"Account is locked. Please try again after {lockoutMinutes} minutes.", ErrorType.Forbidden);
    }

    // The introduction-exchange's Users/Introductions/Payments catalogs are deliberately not ported.
    // Introductions and Payments describe bounties, escrow and connector payouts — concepts the store
    // does not have. Users duplicated what Auth already covers and nothing referenced it. Verified
    // unreferenced before deletion: `grep -rhoE "Error\.(Users|Introductions|Payments)\.[A-Za-z]+"`
    // over src/Store.Api returned nothing, while Error.Auth.* returned 16 distinct members.
}
