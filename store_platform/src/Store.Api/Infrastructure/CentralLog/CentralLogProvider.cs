using System.Collections.Concurrent;
using Microsoft.AspNetCore.Http;
using Store.Api.Common;

namespace Store.Api.Infrastructure.CentralLog;

/// <summary>
/// An <see cref="ILoggerProvider"/> that copies every record onto the estate's central log.
/// Existing sinks are untouched: this is an additional destination, never a replacement, so
/// losing the ingest loses nothing that was being kept before.
/// </summary>
[ProviderAlias("CentralLog")]
public sealed class CentralLogProvider : ILoggerProvider
{
    private readonly CentralLogOptions _options;
    private readonly CentralLogBuffer _queue;
    private readonly IHttpContextAccessor _http;
    private readonly ConcurrentDictionary<string, CentralLogger> _loggers = new(StringComparer.Ordinal);

    public CentralLogProvider(CentralLogOptions options, CentralLogBuffer queue, IHttpContextAccessor http)
    {
        _options = options;
        _queue = queue;
        _http = http;
    }

    public ILogger CreateLogger(string categoryName) =>
        _loggers.GetOrAdd(categoryName, name => new CentralLogger(name, _options, _queue, _http));

    public void Dispose() => _loggers.Clear();
}
