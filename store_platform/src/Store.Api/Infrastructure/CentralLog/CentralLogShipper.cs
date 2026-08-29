using System.Net.Http.Headers;
using System.Text;
using Microsoft.Extensions.Hosting;

namespace Store.Api.Infrastructure.CentralLog;

/// <summary>
/// Drains <see cref="CentralLogBuffer"/> and POSTs NDJSON to the engine's ingest.
///
/// <para>This is the only place in the producer that touches the network, and it runs on its
/// own background task. Every failure mode ends the same way — the batch is dropped and
/// counted — because there is nowhere useful to put a log line about failing to send log
/// lines, and a retry queue would grow without bound during exactly the outage that filled it.</para>
/// </summary>
public sealed class CentralLogShipper : BackgroundService
{
    private readonly CentralLogBuffer _queue;
    private readonly CentralLogOptions _options;
    private readonly IHttpClientFactory? _clients;

    public CentralLogShipper(CentralLogBuffer queue, CentralLogOptions options, IHttpClientFactory? clients = null)
    {
        _queue = queue;
        _options = options;
        _clients = clients;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        if (!_options.Enabled) return;

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await Task.Delay(_options.Interval, stoppingToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                break;
            }

            await FlushAsync(CancellationToken.None).ConfigureAwait(false);
        }

        // One last drain on shutdown, so a deploy does not silently discard the final seconds
        // of whatever was happening when the machine was told to stop.
        await FlushAsync(CancellationToken.None).ConfigureAwait(false);
    }

    public async Task FlushAsync(CancellationToken token)
    {
        while (true)
        {
            var batch = _queue.DrainAvailable(_options.BatchSize);
            if (batch.Count == 0) return;
            await PostAsync(batch, token).ConfigureAwait(false);
            if (batch.Count < _options.BatchSize) return;
        }
    }

    private async Task PostAsync(IReadOnlyList<CentralLogLine> batch, CancellationToken token)
    {
        try
        {
            var body = new StringBuilder();
            foreach (var line in batch) body.Append(line.ToNdjson()).Append('\n');

            using var client = CreateClient();
            using var request = new HttpRequestMessage(HttpMethod.Post, _options.Url)
            {
                Content = new StringContent(body.ToString(), Encoding.UTF8, "application/x-ndjson"),
            };
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _options.ApiKey);

            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(token);
            timeout.CancelAfter(_options.Timeout);
            using var response = await client.SendAsync(request, timeout.Token).ConfigureAwait(false);

            if (response.IsSuccessStatusCode) _queue.CountSent(batch.Count);
            else { _queue.CountFailedPost(); _queue.CountEvicted(batch.Count); }
        }
        catch (Exception)
        {
            // Timeout, DNS, connection refused, a 6PN route that is not up yet: from here they
            // are one failure with one answer.
            _queue.CountFailedPost();
            _queue.CountEvicted(batch.Count);
        }
    }

    private HttpClient CreateClient()
    {
        var client = _clients?.CreateClient(nameof(CentralLogShipper)) ?? new HttpClient();
        client.Timeout = _options.Timeout;
        return client;
    }
}
