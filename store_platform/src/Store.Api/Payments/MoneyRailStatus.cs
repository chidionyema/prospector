namespace Store.Api.Payments;

/// <summary>
/// What the money rail is actually configured to do. Decided ONCE at startup by
/// <see cref="MoneyRailConfigGate"/>, then readable by any probe.
///
/// PAY-1. Before this, live-mode was computed inside the startup gate and reported only to the
/// log. A deploy that shipped a test key took no real money, and nothing outside the log said
/// so: the app booted, /catalog answered 200, checkout completed, and the buyer paid nothing.
/// A log line is not a probe, because nobody reads the log on a green deploy. This turns the
/// answer into a request the deploy can make and fail on.
///
/// It carries no secret. "live" or "test" is already visible to anyone who reaches checkout;
/// the key itself never leaves the gate.
/// </summary>
public sealed class MoneyRailStatus
{
    /// <summary>The active payment provider, e.g. "stripe".</summary>
    public string Provider { get; private set; } = "unknown";

    /// <summary>"live" or "test". Stays "unknown" until the startup gate records a decision.</summary>
    public string Mode { get; private set; } = "unknown";

    /// <summary>The ASP.NET environment name the decision was made in.</summary>
    public string Environment { get; private set; } = "unknown";

    /// <summary>
    /// When the startup gate decided. Null means the gate has not run, which is itself the
    /// answer: an app serving requests with no decision recorded did not run its money guard.
    /// </summary>
    public DateTimeOffset? DecidedAtUtc { get; private set; }

    public void Record(string provider, string mode, string environment, DateTimeOffset decidedAtUtc)
    {
        Provider = provider;
        Mode = mode;
        Environment = environment;
        DecidedAtUtc = decidedAtUtc;
    }
}
