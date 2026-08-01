using System.Security.Cryptography;
using System.Text;
using Microsoft.IdentityModel.Tokens;
using Store.Api.Identity;

namespace Store.Api.Identity;

/// <summary>
/// IJwtSigningKeyProvider that loads the RSA private key from configuration
/// instead of Vault. Ported verbatim from haworks BuildingBlocks/Vault/
/// ConfigJwtSigningKeyProvider.cs — this is the lean, no-Vault key source.
/// Reads <c>Jwt:SigningKeyPem</c> (raw PEM or base64-encoded PEM).
/// </summary>
public sealed class ConfigJwtSigningKeyProvider : IJwtSigningKeyProvider
{
    public string KeyId { get; }
    public RsaSecurityKey SigningKey { get; }
    public JsonWebKey PublicJwk { get; }

    public ConfigJwtSigningKeyProvider(string privateKeyPem, string keyId)
    {
        // Fail here, with the setting named, rather than letting ImportFromPem raise "No supported
        // key formats were found" — which says nothing about which setting is missing. There is
        // deliberately no fallback to a generated key: a generated key boots a misconfigured API
        // that mints tokens no other instance, and no restart of this one, can validate. Loud at
        // startup beats a fleet that silently signs out every customer on deploy.
        if (string.IsNullOrWhiteSpace(privateKeyPem))
        {
            throw new InvalidOperationException(
                "Jwt:SigningKeyPem is not configured. Set the Jwt__SigningKeyPem environment " +
                "variable (or Fly secret) to an RSA private key in PKCS#8 PEM form, raw or " +
                "base64-encoded. Generate one with: openssl genpkey -algorithm RSA " +
                "-pkeyopt rsa_keygen_bits:2048.");
        }

        var pem = privateKeyPem.Contains("-----BEGIN", StringComparison.Ordinal)
            ? privateKeyPem
            : Encoding.UTF8.GetString(Convert.FromBase64String(privateKeyPem));

        var rsa = RSA.Create();
        rsa.ImportFromPem(pem);

        SigningKey = new RsaSecurityKey(rsa) { KeyId = keyId };
        KeyId = keyId;

        var pub = rsa.ExportParameters(includePrivateParameters: false);
        PublicJwk = new JsonWebKey
        {
            Kty = "RSA",
            Use = "sig",
            Alg = SecurityAlgorithms.RsaSha256,
            Kid = keyId,
            N = Base64UrlEncoder.Encode(pub.Modulus!),
            E = Base64UrlEncoder.Encode(pub.Exponent!),
        };
    }

    /// <summary>Generates an ephemeral RSA-2048 provider — used for tests/dev when no PEM is configured.</summary>
    public static ConfigJwtSigningKeyProvider CreateEphemeral(string keyId = "ephemeral-1")
    {
        using var rsa = RSA.Create(2048);
        return new ConfigJwtSigningKeyProvider(rsa.ExportRSAPrivateKeyPem(), keyId);
    }
}
