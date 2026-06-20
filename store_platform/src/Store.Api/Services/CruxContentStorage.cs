using Crux.Storage;

namespace Store.Api.Services;

/// <summary>
/// Adapter that implements the store's <see cref="IContentStorage"/> contract
/// by delegating to Crux's <see cref="IBlobStore"/>. Replaces the hand-rolled
/// <c>R2ContentStorage</c>.
/// </summary>
public sealed class CruxContentStorage : IContentStorage
{
    private readonly IBlobStore _blobStore;

    public CruxContentStorage(IBlobStore blobStore)
    {
        _blobStore = blobStore;
    }

    public bool IsConfigured => _blobStore.IsConfigured;

    public Task<string> CreatePresignedGetUrlAsync(string objectKey, TimeSpan ttl)
    {
        var url = _blobStore.GetDownloadPresignUrl(objectKey, (int)ttl.TotalMinutes);
        return Task.FromResult(url);
    }
}
