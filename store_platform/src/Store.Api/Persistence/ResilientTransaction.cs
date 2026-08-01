using Microsoft.EntityFrameworkCore;
using Store.Api.Common;
using Store.Catalog.Persistence;

namespace Store.Api.Persistence;

/// <summary>
/// <see cref="IResilientTransaction"/> over the request-scoped <see cref="StoreDbContext"/>.
/// The work runs inside that context's execution strategy and an explicit EF transaction, so every
/// operation performed by that same context — including ASP.NET Identity's, since UserManager
/// resolves the same scoped context — commits or rolls back atomically.
/// </summary>
/// <remarks>
/// This is the ONE file of the introduction-exchange auth port that had to be rewritten rather than
/// copied, and the reason is not stylistic. The original wrapped the delegate in an ambient
/// <c>System.Transactions.TransactionScope</c>, which is correct on Npgsql: it enlists, and a scope
/// disposed without <c>Complete()</c> rolls back.
///
/// Microsoft.Data.Sqlite does not implement <c>System.Transactions</c> enlistment, and it does not
/// throw to say so — it ignores the ambient scope entirely. Measured directly against
/// Microsoft.EntityFrameworkCore.Sqlite 9.0.4: a row INSERTed inside a scope that was disposed
/// WITHOUT Complete() was still present afterwards ("ROWS PERSISTED: [written-inside-scope,
/// should-be-rolled-back]"). No exception on either path.
///
/// So the ported code would have compiled, deployed, and read as transactional while providing no
/// atomicity at all. The concrete casualty is ExternalLoginCallbackCommand's create-then-link pair:
/// a failed AddLoginAsync would strand a StoreUser row with EmailConfirmed=true, no password and no
/// external login — an account nobody can sign into, which then permanently blocks that address
/// from registering again because AspNetUsers.NormalizedEmail is UNIQUE.
///
/// <c>BeginTransactionAsync</c> is the provider's own transaction, which SQLite does implement.
/// </remarks>
public sealed class ResilientTransaction(StoreDbContext db) : IResilientTransaction
{
    public Task ExecuteAsync(Func<CancellationToken, Task<bool>> operation, CancellationToken cancellationToken = default)
    {
        var strategy = db.Database.CreateExecutionStrategy();
        return strategy.ExecuteAsync(async () =>
        {
            // Retried in full by the strategy on a transient fault, hence created inside the lambda.
            var tx = await db.Database.BeginTransactionAsync(cancellationToken).ConfigureAwait(false);
            await using (tx.ConfigureAwait(false))
            {
                if (await operation(cancellationToken).ConfigureAwait(false))
                {
                    await tx.CommitAsync(cancellationToken).ConfigureAwait(false);
                }
                else
                {
                    // Explicit rather than relying on dispose: a rollback that matters should be a
                    // statement in the code, not a side effect of a using block going out of scope.
                    await tx.RollbackAsync(cancellationToken).ConfigureAwait(false);
                }
            }
        });
    }
}
