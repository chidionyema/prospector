namespace Store.Api.Services;

/// <summary>
/// Mints short-lived presigned download URLs for purchased content held in object
/// storage (Cloudflare R2). When credentials are absent, <see cref="IsConfigured"/> is
/// false and callers must surface a 503 rather than a buyer-facing error.
/// </summary>
public interface IContentStorage
{
    bool IsConfigured { get; }

    Task<string> CreatePresignedGetUrlAsync(string objectKey, TimeSpan ttl);
}
