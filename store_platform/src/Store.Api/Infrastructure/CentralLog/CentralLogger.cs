using Microsoft.AspNetCore.Http;
using Store.Api.Common;

namespace Store.Api.Infrastructure.CentralLog;

public sealed class CentralLogger : ILogger
{
    private readonly string _category;
    private readonly CentralLogOptions _options;
    private readonly CentralLogBuffer _queue;
    private readonly IHttpContextAccessor _http;
    private readonly bool _selfReferential;

    public CentralLogger(string category, CentralLogOptions options, CentralLogBuffer queue, IHttpContextAccessor http)
    {
        _category = category;
        _options = options;
        _queue = queue;
        _http = http;
        _selfReferential = CentralLogMapper.IsSelfReferential(category);
    }

    IDisposable? ILogger.BeginScope<TState>(TState state) => null;

    public bool IsEnabled(LogLevel logLevel) =>
        _options.Enabled && !_selfReferential && logLevel >= _options.MinimumLevel && logLevel != LogLevel.None;

    public void Log<TState>(
        LogLevel logLevel,
        EventId eventId,
        TState state,
        Exception? exception,
        Func<TState, Exception?, string> formatter)
    {
        if (!IsEnabled(logLevel)) return;

        // Everything from here is wrapped, because a logging call that throws would surface as
        // a failure in whatever it was describing — most dangerously in the money path, where
        // the log line sits between taking a payment and recording it.
        try
        {
            var message = formatter(state, exception);
            var pairs = state as IReadOnlyList<KeyValuePair<string, object?>>;
            var corr = CurrentCorrelationId();
            var line = CentralLogMapper.Map(
                _options.Svc, _category, logLevel, eventId, message, exception, pairs, corr, DateTimeOffset.UtcNow);
            _queue.TryEnqueue(line);
        }
        catch
        {
            // Deliberately silent, and deliberately not logged: the only sink available here is
            // the one that just failed.
        }
    }

    private string? CurrentCorrelationId()
    {
        try
        {
            // The same header the rest of this service already uses (`X-Correlation-Id`,
            // Store.Api.Common.HttpContextExtensions), so one request has one id across the
            // API's own logs, the audit log and the central log.
            return _http.HttpContext?.GetCorrelationId();
        }
        catch (ObjectDisposedException)
        {
            // The request finished while a background continuation was still logging.
            return null;
        }
    }
}
