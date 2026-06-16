using System.Security.Claims;
using Microsoft.AspNetCore.Http;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Store.Api.Infrastructure;
using Store.Catalog.Persistence;

namespace Store.Tests.Infrastructure;

public sealed class IdempotencyFilterTests : IDisposable
{
    private readonly SqliteConnection _connection;
    private readonly DbContextOptions<StoreDbContext> _options;

    public IdempotencyFilterTests()
    {
        _connection = new SqliteConnection("Filename=:memory:");
        _connection.Open();
        _options = new DbContextOptionsBuilder<StoreDbContext>()
            .UseSqlite(_connection)
            .Options;

        using var ctx = new StoreDbContext(_options);
        ctx.Database.EnsureCreated();
    }

    [Fact]
    public async Task InvokeAsync_FirstRequest_Succeeds()
    {
        var services = new ServiceCollection();
        services.AddLogging();
        services.AddDbContext<StoreDbContext>(o => o.UseSqlite(_connection));
        var sp = services.BuildServiceProvider();

        var httpContext = new DefaultHttpContext { RequestServices = sp };
        httpContext.Request.Headers["Idempotency-Key"] = "test-key";
        httpContext.Request.Method = "POST";
        httpContext.Request.Path = "/test";

        var filter = new IdempotencyFilter(required: true);
        var filterCtx = new DefaultEndpointFilterInvocationContext(httpContext, "arg1");

        var nextCalled = 0;
        EndpointFilterDelegate next = (ctx) =>
        {
            nextCalled++;
            return ValueTask.FromResult<object?>(Results.Ok("Success"));
        };

        var result = await filter.InvokeAsync(filterCtx, next);

        Assert.Equal(1, nextCalled);
        Assert.IsType<CapturedResult>(result);
    }

    [Fact]
    public async Task InvokeAsync_ReplayRequest_ReturnsCapturedResult()
    {
        var services = new ServiceCollection();
        services.AddLogging();
        services.AddDbContext<StoreDbContext>(o => o.UseSqlite(_connection));
        var sp = services.BuildServiceProvider();

        var httpContext = new DefaultHttpContext { RequestServices = sp };
        httpContext.Request.Headers["Idempotency-Key"] = "test-key";
        httpContext.Request.Method = "POST";
        httpContext.Request.Path = "/test";

        var filter = new IdempotencyFilter(required: true);
        var filterCtx = new DefaultEndpointFilterInvocationContext(httpContext, "arg1");

        EndpointFilterDelegate next = (ctx) => ValueTask.FromResult<object?>(Results.Ok("Success"));

        // First call
        await filter.InvokeAsync(filterCtx, next);

        // Second call (replay)
        var nextCalled = 0;
        EndpointFilterDelegate nextReplay = (ctx) =>
        {
            nextCalled++;
            return ValueTask.FromResult<object?>(Results.Ok("Should not be called"));
        };

        var result = await filter.InvokeAsync(filterCtx, nextReplay);

        Assert.Equal(0, nextCalled);
        Assert.IsType<CapturedResult>(result);
    }

    [Fact]
    public async Task InvokeAsync_ConcurrentRequest_Returns409()
    {
        var services = new ServiceCollection();
        services.AddLogging();
        services.AddDbContext<StoreDbContext>(o => o.UseSqlite(_connection));
        var sp = services.BuildServiceProvider();

        var httpContext = new DefaultHttpContext { RequestServices = sp };
        httpContext.Request.Headers["Idempotency-Key"] = "test-key";
        httpContext.Request.Method = "POST";
        httpContext.Request.Path = "/test";

        var filter = new IdempotencyFilter(required: true);
        var filterCtx = new DefaultEndpointFilterInvocationContext(httpContext, "arg1");

        // We simulate "InProgress" by manually adding a claim
        using (var ctx = new StoreDbContext(_options))
        {
            // The storage key calculation is internal, but we can just use the same logic or let it fail.
            // Actually, we'll just run one and make it hang if we could, but simpler is to just run one and check.
            // Wait, I'll just use the filter to start one.
        }

        EndpointFilterDelegate nextHang = async (ctx) =>
        {
            // While this is running, another one comes in
            var http2 = new DefaultHttpContext { RequestServices = sp };
            http2.Request.Headers["Idempotency-Key"] = "test-key";
            http2.Request.Method = "POST";
            http2.Request.Path = "/test";
            var filter2 = new IdempotencyFilter(required: true);
            var filterCtx2 = new DefaultEndpointFilterInvocationContext(http2, "arg1");
            
            var result2 = await filter2.InvokeAsync(filterCtx2, (c) => ValueTask.FromResult<object?>(null));
            
            // Should be 409
            Assert.IsType<Microsoft.AspNetCore.Http.HttpResults.ProblemHttpResult>(result2);
            var problem = (Microsoft.AspNetCore.Http.HttpResults.ProblemHttpResult)result2;
            Assert.Equal(409, problem.StatusCode);

            return Results.Ok("Success");
        };

        await filter.InvokeAsync(filterCtx, nextHang);
    }

    public void Dispose()
    {
        _connection.Dispose();
    }
}
