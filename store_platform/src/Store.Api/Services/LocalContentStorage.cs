namespace Store.Api.Services;

/// <summary>
/// Local filesystem content storage for development. Mirrors <see cref="R2ContentStorage"/>'s
/// contract but serves deliverables from a directory on disk via the dev-only
/// GET /dev-content/{key} endpoint. Selected only when R2 is unconfigured AND a local content
/// directory is set (Content:LocalDir / CONTENT_LOCAL_DIR).
///
/// NEVER use this in production: the download URL it mints is unsigned (anyone who knows a
/// content key could fetch it), so the dev-content endpoint that serves these URLs is mapped
/// only in the Development environment. In production R2 presigned URLs serve content instead.
/// </summary>
public sealed class LocalContentStorage : IContentStorage
{
    private readonly string? _root;

    public bool IsConfigured => _root is not null;

    public LocalContentStorage(string? root)
    {
        if (!string.IsNullOrWhiteSpace(root))
        {
            _root = Path.GetFullPath(root);
        }
    }

    public Task<string> CreatePresignedGetUrlAsync(string objectKey, TimeSpan ttl)
    {
        ArgumentException.ThrowIfNullOrEmpty(objectKey);
        if (_root is null)
        {
            throw new InvalidOperationException("Local content storage is not configured.");
        }

        // Relative URL: the buyer's browser follows the redirect back to this host's
        // dev-content endpoint, which streams the file from disk. The object key
        // (packs/<id>/<sha>.zip) is engine-controlled and path-safe; ResolvePath enforces
        // containment as defence in depth.
        return Task.FromResult($"/dev-content/{objectKey}");
    }

    /// <summary>
    /// Resolve an objectKey to a physical path, refusing any path that escapes the root
    /// (path-traversal guard). Returns null when unconfigured or out of bounds.
    /// </summary>
    public string? ResolvePath(string objectKey)
    {
        if (_root is null || string.IsNullOrEmpty(objectKey))
        {
            return null;
        }

        var full = Path.GetFullPath(Path.Combine(_root, objectKey));
        var rootWithSep = _root.EndsWith(Path.DirectorySeparatorChar)
            ? _root
            : _root + Path.DirectorySeparatorChar;
        if (!full.StartsWith(rootWithSep, StringComparison.Ordinal))
        {
            return null;
        }
        return full;
    }
}
