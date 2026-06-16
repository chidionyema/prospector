using System.Security.Cryptography;

namespace Store.Api.Services;

/// <summary>256-bit CSPRNG tokens, base64url-encoded. Non-guessable and URL-safe.</summary>
public sealed class TokenGenerator : ITokenGenerator
{
    public string NewToken()
    {
        var bytes = RandomNumberGenerator.GetBytes(32);
        return Convert.ToBase64String(bytes)
            .Replace('+', '-')
            .Replace('/', '_')
            .TrimEnd('=');
    }
}
