using Microsoft.Extensions.Configuration;

namespace Store.Api.Services;

/// <summary>
/// Maps this deployment's Cloudflare R2 credentials (supplied as <c>R2_*</c> env vars / <c>R2:*</c>
/// config, see DEPLOYMENT.md) onto the <c>Storage:*</c> keys that Crux.Storage reads, composing
/// the R2 endpoint from the account id. This lets existing deployments keep working with no ops
/// change after the move from the hand-rolled R2ContentStorage to Crux.Storage.
/// </summary>
public static class R2StorageBridge
{
    /// <summary>
    /// Returns the <c>Storage:*</c> overrides derived from R2 config, or an EMPTY dictionary when no
    /// R2 account is configured (e.g. dev) or a <c>Storage:ServiceUrl</c> is already set explicitly
    /// (an explicit Storage config always wins).
    /// </summary>
    public static IReadOnlyDictionary<string, string?> BuildStorageOverrides(IConfiguration config)
    {
        ArgumentNullException.ThrowIfNull(config);

        var account = Read(config, "R2:AccountId", "R2_ACCOUNT_ID");
        if (string.IsNullOrEmpty(account) || !string.IsNullOrEmpty(config["Storage:ServiceUrl"]))
        {
            return new Dictionary<string, string?>(StringComparer.Ordinal);
        }

        var accessKey = Read(config, "R2:AccessKeyId", "R2_ACCESS_KEY_ID");
        var secretKey = Read(config, "R2:SecretAccessKey", "R2_SECRET_ACCESS_KEY");
        var bucket = Read(config, "R2:Bucket", "R2_BUCKET");

        // All-or-nothing (matches the old R2ContentStorage invariant): a PARTIAL R2 config must
        // not produce a half-built Storage config (e.g. a null bucket), which Crux.Storage would
        // turn into malformed presigned URLs / a cryptic 403 instead of the clean "storage
        // unconfigured" 503. Treat partial R2 config as unconfigured.
        if (string.IsNullOrEmpty(accessKey) || string.IsNullOrEmpty(secretKey) || string.IsNullOrEmpty(bucket))
        {
            return new Dictionary<string, string?>(StringComparer.Ordinal);
        }

        return new Dictionary<string, string?>(StringComparer.Ordinal)
        {
            ["Storage:ServiceUrl"] = $"https://{account}.r2.cloudflarestorage.com",
            ["Storage:AccessKey"] = accessKey,
            ["Storage:SecretKey"] = secretKey,
            ["Storage:BucketName"] = bucket,
            // R2 uses the pseudo-region "auto"; Crux.Storage sets AuthenticationRegion="auto"
            // for SigV4 so presigned URLs validate against R2.
            ["Storage:Region"] = "auto",
        };
    }

    private static string? Read(IConfiguration config, string key, string env) =>
        config[key] ?? Environment.GetEnvironmentVariable(env);
}
