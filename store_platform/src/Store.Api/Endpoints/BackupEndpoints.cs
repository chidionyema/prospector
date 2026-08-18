using System.Formats.Tar;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using Microsoft.Data.Sqlite;

namespace Store.Api.Endpoints;

/// <summary>
/// Portable backup fetch for the money database and the Data Protection key ring.
///
/// These two artifacts used to be pulled with `fly ssh sftp get`. That worked, and it tied the
/// estate's disaster recovery to one platform's CLI: the engine container deliberately carries
/// no platform binary, so the nightly offsite backup could not fetch either of them from where
/// it actually runs, and they were bridged by hand from the laptop instead.
///
/// An authenticated HTTPS GET works from anywhere with a network and a key. It is the same
/// contract on Fly, on a rented Linux box, or on a laptop.
/// </summary>
public static class BackupEndpoints
{
    public static void MapBackupEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/internal/backup/database", GetDatabase);
        app.MapGet("/internal/backup/keyring", GetKeyring);
    }

    // Same shape as every other /internal endpoint: a shared key in X-Internal-Key, compared in
    // fixed time, and FAIL CLOSED when no key is configured. An unauthenticated version of this
    // endpoint would hand out every order, every entitlement and the key ring that decrypts
    // grant tokens, so "no key configured" must never mean "no check".
    private static IResult? Reject(HttpRequest http, IConfiguration config)
    {
        var expectedKey = config["Store:InternalApiKey"]
            ?? Environment.GetEnvironmentVariable("STORE_INTERNAL_API_KEY");
        if (string.IsNullOrEmpty(expectedKey))
        {
            return Results.Problem("Internal API key not configured",
                statusCode: StatusCodes.Status503ServiceUnavailable);
        }

        var providedKey = http.Headers["X-Internal-Key"].ToString();
        if (string.IsNullOrEmpty(providedKey) ||
            !CryptographicOperations.FixedTimeEquals(
                Encoding.UTF8.GetBytes(providedKey),
                Encoding.UTF8.GetBytes(expectedKey)))
        {
            return Results.Unauthorized();
        }

        return null;
    }

    private static async Task<IResult> GetDatabase(
        HttpRequest http, IConfiguration config, ILoggerFactory loggerFactory)
    {
        var rejected = Reject(http, config);
        if (rejected is not null) return rejected;

        var log = loggerFactory.CreateLogger("Backup");
        var connectionString = config.GetConnectionString("DefaultConnection") ?? "Data Source=store.db";
        var source = new SqliteConnectionStringBuilder(connectionString).DataSource;
        if (!File.Exists(source))
        {
            log.LogError("Backup requested but no database at {Source}", source);
            return Results.Problem($"No database at {source}", statusCode: StatusCodes.Status500InternalServerError);
        }

        // VACUUM INTO, not File.Copy. The database is live and being written to while this
        // runs, and a byte-for-byte copy of a live SQLite file can be torn across a page
        // boundary. VACUUM INTO takes a read transaction and writes a consistent, already
        // compacted snapshot. The offsite backup runs PRAGMA integrity_check on what it
        // receives, so a torn copy would be rejected on arrival anyway - this is what makes
        // the copy good rather than what detects that it was bad.
        var snapshot = Path.Combine(Path.GetTempPath(), $"backup-{Guid.NewGuid():N}.db");
        try
        {
            var conn = new SqliteConnection(connectionString);
            await using (conn.ConfigureAwait(false))
            {
                await conn.OpenAsync().ConfigureAwait(false);
                var cmd = conn.CreateCommand();
                // The path is a server-side temp name this method just generated, never
                // caller input, and VACUUM INTO takes no parameter binding.
                cmd.CommandText = $"VACUUM INTO '{snapshot.Replace("'", "''")}'";
                await cmd.ExecuteNonQueryAsync().ConfigureAwait(false);
            }

            var bytes = await File.ReadAllBytesAsync(snapshot).ConfigureAwait(false);
            log.LogInformation("Served database backup, {Bytes} bytes", bytes.Length);
            return Results.File(bytes, "application/octet-stream", "store.db");
        }
        finally
        {
            // Read fully into memory and delete before returning, rather than streaming the
            // file and deleting after. The database is a few megabytes, and a streamed handle
            // left behind on a cancelled request fills the container's temp space over time.
            try { File.Delete(snapshot); } catch (IOException) { /* temp file, best effort */ }
        }
    }

    private static async Task<IResult> GetKeyring(
        HttpRequest http, IConfiguration config, ILoggerFactory loggerFactory)
    {
        var rejected = Reject(http, config);
        if (rejected is not null) return rejected;

        var log = loggerFactory.CreateLogger("Backup");
        var keysDir = config["DataProtection:KeyPath"] ?? "/data/keys";
        if (!Directory.Exists(keysDir))
        {
            log.LogError("Backup requested but no key ring at {Dir}", keysDir);
            return Results.Problem($"No key ring at {keysDir}", statusCode: StatusCodes.Status500InternalServerError);
        }

        // Same .tar.gz the old `fly ssh console -C "tar -czf ..."` produced, so the restore
        // procedure and everything already in the bucket stay one format.
        using var buffer = new MemoryStream();
        var gzip = new GZipStream(buffer, CompressionLevel.Optimal, leaveOpen: true);
        await using (gzip.ConfigureAwait(false))
        {
            await TarFile.CreateFromDirectoryAsync(keysDir, gzip, includeBaseDirectory: true).ConfigureAwait(false);
        }

        var bytes = buffer.ToArray();
        log.LogInformation("Served key ring backup, {Bytes} bytes", bytes.Length);
        return Results.File(bytes, "application/gzip", "keyring.tgz");
    }
}
