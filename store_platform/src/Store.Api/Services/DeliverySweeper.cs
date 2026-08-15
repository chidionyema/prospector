using System.Globalization;

namespace Store.Api.Services;

/// <summary>
/// Runs <see cref="DeliveryDrain"/> on a timer. Deliberately thin: all of the decision-making
/// lives in the drain, which is a scoped service and therefore directly testable without a host.
///
/// The interval is config-declared (<c>Delivery:SweepSeconds</c>, default 30) rather than a
/// constant, so a test can run it fast and an operator can shorten it without a deploy.
///
/// Nothing here may throw. A background service that faults is torn down by the host and stops
/// sweeping -- which would leave the outbox filling with links nobody sends, the exact failure
/// this whole mechanism exists to remove.
/// </summary>
public sealed class DeliverySweeper(
    IServiceScopeFactory scopeFactory,
    IConfiguration config,
    ILogger<DeliverySweeper> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var interval = TimeSpan.FromSeconds(
            int.TryParse(config["Delivery:SweepSeconds"], CultureInfo.InvariantCulture, out var seconds)
            && seconds > 0
                ? seconds
                : 30);

        logger.LogInformation(
            "Delivery sweeper started; draining the fulfilment outbox every {Seconds}s.",
            interval.TotalSeconds);

        using var timer = new PeriodicTimer(interval);
        // Drain once immediately: on a restart there may already be links owed from before the
        // process died, and that is precisely the case this exists for.
        do
        {
            await DrainOnceAsync(stoppingToken).ConfigureAwait(false);
        }
        while (await WaitAsync(timer, stoppingToken).ConfigureAwait(false));
    }

    private async Task DrainOnceAsync(CancellationToken stoppingToken)
    {
        try
        {
            using var scope = scopeFactory.CreateScope();
            var drain = scope.ServiceProvider.GetRequiredService<DeliveryDrain>();
            var result = await drain.DrainAsync(stoppingToken).ConfigureAwait(false);
            if (result.Sent > 0 || result.Failed > 0)
            {
                logger.LogInformation(
                    "Delivery sweep: {Sent} sent, {Failed} failed, {Skipped} skipped.",
                    result.Sent, result.Failed, result.Skipped);
            }
        }
        catch (OperationCanceledException)
        {
            // Shutdown. The rows are durable; the next process drains them.
        }
#pragma warning disable CA1031 // a faulted sweeper stops sweeping, which is the failure being fixed
        catch (Exception ex)
#pragma warning restore CA1031
        {
            logger.LogError(ex, "Delivery sweep failed; the queued links remain queued.");
        }
    }

    private static async Task<bool> WaitAsync(PeriodicTimer timer, CancellationToken stoppingToken)
    {
        try
        {
            return await timer.WaitForNextTickAsync(stoppingToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            return false;
        }
    }
}
