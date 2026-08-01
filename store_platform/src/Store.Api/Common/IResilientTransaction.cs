namespace Store.Api.Common;

/// <summary>
/// Runs a unit of work inside the database's retrying execution strategy plus a transaction,
/// so it is atomic AND automatically retried on a transient fault (serialization failure,
/// deadlock, dropped connection). Required wherever a handler opens its own transaction — an
/// explicit transaction or an ambient <c>TransactionScope</c> — because once retry-on-failure
/// is enabled, EF rejects user-initiated transactions that are not wrapped in the strategy.
/// The implementation uses the request-scoped context's strategy, so operations performed by
/// that same context (e.g. ASP.NET Identity's UserManager) enlist correctly.
/// </summary>
public interface IResilientTransaction
{
    /// <summary>
    /// Runs <paramref name="operation"/> inside the retrying strategy and a transaction. The
    /// transaction commits only if the operation returns <c>true</c>; returning <c>false</c>
    /// rolls it back (e.g. a later step failed and earlier writes must be undone).
    /// </summary>
    Task ExecuteAsync(Func<CancellationToken, Task<bool>> operation, CancellationToken cancellationToken = default);
}
