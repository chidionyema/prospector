using Amazon.Runtime;
using Amazon.S3;
using Amazon.S3.Model;

namespace Store.Api.Services;

/// <summary>
/// Cloudflare R2 (S3-compatible) presigned download URLs. Constructed once (singleton).
/// If any credential is missing it stays unconfigured and callers surface a 503 — it
/// never throws at startup, so the rest of the store runs in dev without R2 wired.
/// </summary>
public sealed class R2ContentStorage : IContentStorage, IDisposable
{
    private readonly AmazonS3Client? _client;
    private readonly string _bucket;

    public bool IsConfigured => _client is not null;

    public R2ContentStorage(IConfiguration config)
    {
        ArgumentNullException.ThrowIfNull(config);

        var accountId = Read(config, "R2:AccountId", "R2_ACCOUNT_ID");
        var accessKey = Read(config, "R2:AccessKeyId", "R2_ACCESS_KEY_ID");
        var secretKey = Read(config, "R2:SecretAccessKey", "R2_SECRET_ACCESS_KEY");
        _bucket = Read(config, "R2:Bucket", "R2_BUCKET") ?? "";

        if (string.IsNullOrEmpty(accountId) || string.IsNullOrEmpty(accessKey)
            || string.IsNullOrEmpty(secretKey) || string.IsNullOrEmpty(_bucket))
        {
            return;
        }

        var s3Config = new AmazonS3Config
        {
            ServiceURL = $"https://{accountId}.r2.cloudflarestorage.com",
            ForcePathStyle = true,
            AuthenticationRegion = "auto",
        };
        _client = new AmazonS3Client(new BasicAWSCredentials(accessKey, secretKey), s3Config);
    }

    public Task<string> CreatePresignedGetUrlAsync(string objectKey, TimeSpan ttl)
    {
        ArgumentException.ThrowIfNullOrEmpty(objectKey);
        if (_client is null)
        {
            throw new InvalidOperationException("R2 content storage is not configured.");
        }

        var request = new GetPreSignedUrlRequest
        {
            BucketName = _bucket,
            Key = objectKey,
            Verb = HttpVerb.GET,
            Expires = DateTime.UtcNow.Add(ttl),
        };
        return _client.GetPreSignedURLAsync(request);
    }

    private static string? Read(IConfiguration config, string key, string envVar) =>
        config[key] ?? Environment.GetEnvironmentVariable(envVar);

    public void Dispose()
    {
        _client?.Dispose();
        GC.SuppressFinalize(this);
    }
}
