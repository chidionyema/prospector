using System.Threading.Channels;

namespace Store.Api.Infrastructure.CentralLog;

/// <summary>
/// The buffer between a request thread and the network.
///
/// <para>The whole point of this class is that <see cref="TryEnqueue"/> does no I/O, takes no
/// lock a caller can wait on, and cannot throw. A request that logs must not become a request
/// that waits on, or fails because of, a logging endpoint. When the buffer is full the OLDEST
/// line is discarded and counted, because during an incident the newest lines are the ones
/// describing it.</para>
/// </summary>
public sealed class CentralLogBuffer
{
    private readonly Channel<CentralLogLine> _channel;
    private long _enqueued;
    private long _dropped;
    private long _sent;
    private long _failedPosts;

    public CentralLogBuffer(CentralLogOptions options)
    {
        _channel = Channel.CreateBounded<CentralLogLine>(new BoundedChannelOptions(options.Capacity)
        {
            FullMode = BoundedChannelFullMode.DropOldest,
            SingleReader = true,
            SingleWriter = false,
        });
    }

    public long Enqueued => Interlocked.Read(ref _enqueued);
    public long Dropped => Interlocked.Read(ref _dropped);
    public long Sent => Interlocked.Read(ref _sent);
    public long FailedPosts => Interlocked.Read(ref _failedPosts);

    public void TryEnqueue(CentralLogLine line)
    {
        // DropOldest makes TryWrite always succeed while the channel is open, so a false here
        // means the writer is completed, not that we are full. A full channel silently evicts,
        // which is why Dropped is derived from the count rather than from this return value.
        if (_channel.Writer.TryWrite(line)) Interlocked.Increment(ref _enqueued);
        else Interlocked.Increment(ref _dropped);
    }

    public void CountEvicted(long n) => Interlocked.Add(ref _dropped, n);
    public void CountSent(long n) => Interlocked.Add(ref _sent, n);
    public void CountFailedPost() => Interlocked.Increment(ref _failedPosts);

    public ChannelReader<CentralLogLine> Reader => _channel.Reader;

    public void Complete() => _channel.Writer.TryComplete();

    /// <summary>Drains up to <paramref name="max"/> lines that are already buffered.</summary>
    public IReadOnlyList<CentralLogLine> DrainAvailable(int max)
    {
        var batch = new List<CentralLogLine>();
        while (batch.Count < max && _channel.Reader.TryRead(out var line)) batch.Add(line);
        return batch;
    }
}
