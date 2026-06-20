using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using Crux.Storage;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Store.Api.Services;
using Xunit;

namespace Store.Tests.Services;

/// <summary>
/// Proves the money/download path after the move from the hand-rolled R2ContentStorage to
/// Crux.Storage: the R2_* deployment config is bridged onto Crux's Storage:* section, and
/// the resulting presigned download URL is correctly formed for Cloudflare R2 (right host, bucket,
/// key, 5-minute expiry, and — critically — the "auto" SigV4 signing region R2 requires).
///
/// Presigned URL generation is offline (HMAC signing); no network or real R2 account is needed.
/// </summary>
public sealed class StorageWiringTests
{
    private const string Account = "abc123account";
    private const string Bucket = "prospector-packs";
    private const string ObjectKey = "packs/pack-1/deadbeef.zip";

    // ---- R2StorageBridge mapping ------------------------------------------------------------

    [Fact]
    public void Bridge_maps_R2_config_onto_Storage_section_and_composes_endpoint()
    {
        var config = BuildR2Config();

        var overrides = R2StorageBridge.BuildStorageOverrides(config);

        Assert.Equal($"https://{Account}.r2.cloudflarestorage.com", overrides["Storage:ServiceUrl"]);
        Assert.Equal("AKIATESTKEY", overrides["Storage:AccessKey"]);
        Assert.Equal("test-secret-key", overrides["Storage:SecretKey"]);
        Assert.Equal(Bucket, overrides["Storage:BucketName"]);
        Assert.Equal("auto", overrides["Storage:Region"]);
    }

    [Fact]
    public void Bridge_is_noop_when_no_R2_account_configured()
    {
        // The bridge falls back to R2_* env vars when config is absent (by design), and real R2
        // creds live in the shell profile on this machine — so clear them for a hermetic check that
        // "no R2 account anywhere" yields no overrides. Restored in finally.
        var saved = ClearR2Env();
        try
        {
            var config = new ConfigurationBuilder().Build();

            var overrides = R2StorageBridge.BuildStorageOverrides(config);

            Assert.Empty(overrides);
        }
        finally
        {
            RestoreR2Env(saved);
        }
    }

    private static readonly string[] R2EnvVars =
        { "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET" };

    private static Dictionary<string, string?> ClearR2Env()
    {
        var saved = new Dictionary<string, string?>(StringComparer.Ordinal);
        foreach (var name in R2EnvVars)
        {
            saved[name] = Environment.GetEnvironmentVariable(name);
            Environment.SetEnvironmentVariable(name, null);
        }
        return saved;
    }

    private static void RestoreR2Env(Dictionary<string, string?> saved)
    {
        foreach (var kvp in saved)
        {
            Environment.SetEnvironmentVariable(kvp.Key, kvp.Value);
        }
    }

    [Fact]
    public void Bridge_does_not_override_explicit_Storage_config()
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>(StringComparer.Ordinal)
            {
                ["R2:AccountId"] = Account,
                ["Storage:ServiceUrl"] = "https://explicit.example.com",
            })
            .Build();

        var overrides = R2StorageBridge.BuildStorageOverrides(config);

        Assert.Empty(overrides);
    }

    // ---- End-to-end: bridge -> AddCruxStorage -> IContentStorage presigned URL ----------

    [Fact]
    public async Task Download_presigned_url_is_correctly_formed_for_R2()
    {
        var storage = BuildContentStorageFromR2Config();

        Assert.True(storage.IsConfigured);

        var url = await storage.CreatePresignedGetUrlAsync(ObjectKey, TimeSpan.FromMinutes(5));

        Assert.StartsWith("https://", url, StringComparison.Ordinal);
        // R2 endpoint composed from the account id.
        Assert.Contains($"{Account}.r2.cloudflarestorage.com", url, StringComparison.Ordinal);
        // Path-style addressing puts the bucket + object key in the path.
        Assert.Contains(Bucket, url, StringComparison.Ordinal);
        Assert.Contains("packs/pack-1/deadbeef.zip", url, StringComparison.Ordinal);
        // SigV4 presigned URL markers.
        Assert.Contains("X-Amz-Signature=", url, StringComparison.Ordinal);
        Assert.Contains("X-Amz-Algorithm=AWS4-HMAC-SHA256", url, StringComparison.Ordinal);
        // 5-minute TTL == 300 seconds.
        Assert.Contains("X-Amz-Expires=300", url, StringComparison.Ordinal);
        // THE money-path regression proof: the credential scope must sign with region "auto".
        // If AuthenticationRegion="auto" did not take effect, this scope would read a real region
        // (e.g. us-east-1) and R2 would reject the signature. The scope's slashes are percent-encoded
        // in the query string, so match the encoded form: .../auto/s3/aws4_request.
        Assert.Contains("auto%2Fs3%2Faws4_request", url, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Download_url_honours_a_custom_ttl()
    {
        var storage = BuildContentStorageFromR2Config();

        var url = await storage.CreatePresignedGetUrlAsync(ObjectKey, TimeSpan.FromMinutes(10));

        Assert.Contains("X-Amz-Expires=600", url, StringComparison.Ordinal);
    }

    // ---- helpers ----------------------------------------------------------------------------

    private static IConfiguration BuildR2Config() =>
        new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>(StringComparer.Ordinal)
            {
                ["R2:AccountId"] = Account,
                ["R2:AccessKeyId"] = "AKIATESTKEY",
                ["R2:SecretAccessKey"] = "test-secret-key",
                ["R2:Bucket"] = Bucket,
            })
            .Build();

    /// <summary>
    /// Reproduces the exact Program.cs wiring: start from R2:* config, apply the bridge overrides,
    /// AddCruxStorage, then wrap the resolved IBlobStore in the store's CruxContentStorage.
    /// </summary>
    private static CruxContentStorage BuildContentStorageFromR2Config()
    {
        var builder = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>(StringComparer.Ordinal)
            {
                ["R2:AccountId"] = Account,
                ["R2:AccessKeyId"] = "AKIATESTKEY",
                ["R2:SecretAccessKey"] = "test-secret-key",
                ["R2:Bucket"] = Bucket,
            });
        var preBridge = builder.Build();
        var overrides = R2StorageBridge.BuildStorageOverrides(preBridge);
        builder.AddInMemoryCollection(overrides);
        var config = builder.Build();

        var services = new ServiceCollection();
        services.AddCruxStorage(config);
        var provider = services.BuildServiceProvider();

        var blobStore = provider.GetRequiredService<IBlobStore>();
        return new CruxContentStorage(blobStore);
    }
}
