using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Store.Catalog.Domain;
using Store.Catalog.Persistence;

namespace Store.Api.Infrastructure;

public sealed class IdempotencyFilter(bool required)
{
    private const string HeaderName = "Idempotency-Key";
    private const int MaxKeyLength = 200;
    private static readonly TimeSpan Ttl = TimeSpan.FromHours(96);

    public async ValueTask<object?> InvokeAsync(EndpointFilterInvocationContext ctx, EndpointFilterDelegate next)
    {
        var http = ctx.HttpContext;
        var clientKey = http.Request.Headers[HeaderName].ToString();

        if (string.IsNullOrWhiteSpace(clientKey))
        {
            return required
                ? Results.Problem(
                    detail: $"An {HeaderName} header is required for this operation.",
                    statusCode: StatusCodes.Status400BadRequest)
                : await next(ctx).ConfigureAwait(false);
        }

        if (clientKey.Length > MaxKeyLength)
            return Results.Problem($"{HeaderName} must be at most {MaxKeyLength} characters.",
                statusCode: StatusCodes.Status400BadRequest);

        var scope = http.User.FindFirstValue(ClaimTypes.NameIdentifier) ?? "anon";
        var method = http.Request.Method;
        var path = http.Request.Path.Value ?? "";
        var storageKey = Hash($"{scope}|{method}|{path}|{clientKey}");
        var fingerprint = ComputeFingerprint(method, path, ctx.Arguments);

        using var scope_db = http.RequestServices.CreateScope();
        var db = scope_db.ServiceProvider.GetRequiredService<StoreDbContext>();

        var result = await TryGetExistingAsync(db, storageKey, fingerprint).ConfigureAwait(false);
        if (result != null) return result;

        return await ExecuteAndRecordAsync(db, ctx, next, storageKey, method, path).ConfigureAwait(false);
    }

    private static async Task<object?> TryGetExistingAsync(StoreDbContext db, string storageKey, string fingerprint)
    {
        // Phase 1 — claim the key (INSERT).
        var claim = new IdempotencyJournalEntry
        {
            IdempotencyKey = storageKey,
            CommandType = "Initial", // Will be updated if we succeed
            Status = IdempotencyJournalEntry.StatusInProgress,
            RequestFingerprint = fingerprint,
            CreatedAt = DateTime.UtcNow,
            ExpiresAt = DateTime.UtcNow.Add(Ttl)
        };
        db.IdempotencyJournal.Add(claim);
        try
        {
            await db.SaveChangesAsync().ConfigureAwait(false);
            return null; // Successfully claimed
        }
        catch (DbUpdateException ex) when (IsUniqueViolation(ex))
        {
            db.Entry(claim).State = EntityState.Detached;
            var existing = await db.IdempotencyJournal.AsNoTracking()
                .FirstOrDefaultAsync(e => e.IdempotencyKey == storageKey).ConfigureAwait(false);
            
            if (existing is null) throw;

            if (!string.Equals(existing.RequestFingerprint, fingerprint, StringComparison.Ordinal))
                return Results.Problem(
                    $"This {HeaderName} was already used for a different request.",
                    statusCode: StatusCodes.Status422UnprocessableEntity);

            if (string.Equals(existing.Status, IdempotencyJournalEntry.StatusCompleted, StringComparison.Ordinal))
                return Replay(existing);

            return Results.Problem(
                $"A request with this {HeaderName} is still being processed. Retry shortly.",
                statusCode: StatusCodes.Status409Conflict);
        }
    }

    private static async Task<object?> ExecuteAndRecordAsync(
        StoreDbContext db,
        EndpointFilterInvocationContext ctx,
        EndpointFilterDelegate next,
        string storageKey,
        string method,
        string path)
    {
        var claim = await db.IdempotencyJournal.FindAsync(storageKey).ConfigureAwait(false) ?? throw new InvalidOperationException("Claim vanished");
        claim.CommandType = $"{method} {path}";

        try
        {
            var (statusCode, contentType, body) = await CaptureAsync(ctx, next).ConfigureAwait(false);

            claim.Status = IdempotencyJournalEntry.StatusCompleted;
            claim.StatusCode = statusCode;
            claim.ContentType = contentType;
            claim.ResponseBodyBase64 = Convert.ToBase64String(body);
            await db.SaveChangesAsync().ConfigureAwait(false);

            return new CapturedResult(statusCode, contentType, body);
        }
        catch
        {
            try
            {
                db.IdempotencyJournal.Remove(claim);
                await db.SaveChangesAsync(CancellationToken.None).ConfigureAwait(false);
            }
            catch { /* best-effort cleanup */ }
            throw;
        }
    }

    private static async Task<(int StatusCode, string? ContentType, byte[] Body)> CaptureAsync(
        EndpointFilterInvocationContext ctx, EndpointFilterDelegate next)
    {
        var http = ctx.HttpContext;
        var originalBody = http.Response.Body;
        using var buffer = new MemoryStream();
        http.Response.Body = buffer;
        try
        {
            var result = await next(ctx).ConfigureAwait(false);
            if (result is IResult r) await r.ExecuteAsync(http).ConfigureAwait(false);
            else if (result is not null) await Results.Json(result).ExecuteAsync(http).ConfigureAwait(false);
        }
        finally
        {
            http.Response.Body = originalBody;
        }
        return (http.Response.StatusCode, http.Response.ContentType, buffer.ToArray());
    }

    private static CapturedResult Replay(IdempotencyJournalEntry e)
    {
        var body = e.ResponseBodyBase64 is not null ? Convert.FromBase64String(e.ResponseBodyBase64) : [];
        return new CapturedResult(e.StatusCode ?? StatusCodes.Status200OK, e.ContentType, body);
    }

    private static string ComputeFingerprint(string method, string path, IList<object?> args)
    {
        var sb = new StringBuilder(method).Append('\n').Append(path);
        foreach (var arg in args)
        {
            if (arg is null) continue;
            var type = arg.GetType();
            if (type.Namespace?.StartsWith("Store.Api.Contracts", StringComparison.Ordinal) == true)
                sb.Append('\n').Append(JsonSerializer.Serialize(arg, type));
        }
        return Hash(sb.ToString());
    }

    private static string Hash(string input) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(input)));

    private static bool IsUniqueViolation(DbUpdateException ex)
    {
        return ex.InnerException?.Message.Contains("UNIQUE constraint failed", StringComparison.Ordinal) == true
               || ex.InnerException?.Message.Contains("23505", StringComparison.Ordinal) == true;
    }
}
