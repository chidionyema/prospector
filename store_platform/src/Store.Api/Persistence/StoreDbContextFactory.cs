using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Design;
using Store.Catalog.Persistence;

namespace Store.Api.Persistence;

/// <summary>
/// Design-time factory so `dotnet ef migrations` can build the context WITHOUT booting the
/// Store.Api web host (whose top-level Program runs the server). Lives in Store.Api because
/// that project carries the EFCore.Design package. The connection string here only selects
/// the SQLite provider for scaffolding; it is never used at runtime.
/// </summary>
public sealed class StoreDbContextFactory : IDesignTimeDbContextFactory<StoreDbContext>
{
    public StoreDbContext CreateDbContext(string[] args)
    {
        var options = new DbContextOptionsBuilder<StoreDbContext>()
            .UseSqlite("Data Source=store.db")
            .Options;
        return new StoreDbContext(options);
    }
}
