using Microsoft.Extensions.Configuration;
using Store.Api.Infrastructure;
using Xunit;

namespace Store.Tests.Infrastructure;

/// <summary>
/// Incident tests for the API's secrets-as-files path, plus the three measurements this estate had
/// been assuming rather than checking.
///
/// WHY THESE AND NOT MORE. `~/AGENTS.md`'s ladder puts example tests of orchestration at the bottom
/// and incident tests at rung 4. Nothing here tests that a method returns what it returns. Each case
/// below is either a failure that has already happened on this estate — a mount that arrived empty
/// while the deploy reported success, 2026-08-24 — or a claim about someone else's library that the
/// manifest in deploy/k8s/base/api.yaml now depends on being true.
///
/// NO REAL CREDENTIAL APPEARS HERE. Every value written below is a literal test string.
/// </summary>
public sealed class FileSecretsTests : IDisposable
{
    private readonly string _root = Path.Combine(
        Path.GetTempPath(), "file-secrets-tests-" + Guid.NewGuid().ToString("n"));

    public void Dispose()
    {
        if (Directory.Exists(_root))
        {
            Directory.Delete(_root, recursive: true);
        }
    }

    // The analyser (CA1861) refuses an inline array literal in a repeatedly-called assert.
    private static readonly string[] UnderscoreNames = ["Jwt__SigningKeyPem", "Store__InternalApiKey"];
    private static readonly string[] ProjectedNames = ["Jwt__SigningKeyPem", "MAILJET_API_KEY"];

    private string NewDir(string name)
    {
        var path = Path.Combine(_root, name);
        Directory.CreateDirectory(path);
        return path;
    }

    // ---------------------------------------------------------------------------------------
    // The refusals. Each one is the 2026-08-24 incident in a different disguise: a box that came
    // up carrying none of its settings while the thing that deployed it reported success.
    // ---------------------------------------------------------------------------------------

    [Fact]
    public void NoDirectoryNamed_IsANoOp_SoLaptopsAndCiAreUnaffected()
    {
        var builder = new ConfigurationBuilder();

        var names = builder.AddFileSecrets(directory: "");

        Assert.Empty(names);
        Assert.Empty(builder.Sources);
    }

    [Fact]
    public void DirectoryDoesNotExist_RefusesToStart()
    {
        var missing = Path.Combine(_root, "never-mounted");

        var ex = Assert.Throws<InvalidOperationException>(
            () => new ConfigurationBuilder().AddFileSecrets(missing));

        // The message names the variable and the path so an operator can see WHICH of the two
        // sides disagreed. It must never name a value, because there is nothing to name.
        Assert.Contains(FileSecrets.DirectoryVariable, ex.Message, StringComparison.Ordinal);
        Assert.Contains(missing, ex.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void DirectoryExistsButIsEmpty_RefusesToStart()
    {
        // This is the shape a misnamed Secret takes. It is indistinguishable from success to
        // everything downstream, which is why it has to fail here and not later.
        var empty = NewDir("mounted-but-empty");

        var ex = Assert.Throws<InvalidOperationException>(
            () => new ConfigurationBuilder().AddFileSecrets(empty));

        Assert.Contains("empty directory", ex.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void DirectoryHoldsOnlyKubernetesMachinery_CountsAsEmpty()
    {
        // Mid-rotation a projected volume can hold the ".."-prefixed entries and nothing else.
        // Treating that as a loaded secret set is the empty-mount failure with extra steps.
        var dir = NewDir("machinery-only");
        Directory.CreateDirectory(Path.Combine(dir, "..2026_08_24_09_11_02.123456789"));

        Assert.Throws<InvalidOperationException>(
            () => new ConfigurationBuilder().AddFileSecrets(dir));
    }

    // ---------------------------------------------------------------------------------------
    // The claims deploy/k8s/base/api.yaml depends on. These are about
    // Microsoft.Extensions.Configuration.KeyPerFile, not about code written here, and that is
    // exactly why they are worth a test: the manifest bets on them.
    // ---------------------------------------------------------------------------------------

    [Fact]
    public void DoubleUnderscoreInAFilenameBecomesAConfigurationColon()
    {
        // The whole reason no resolver had to be written. `kubectl create secret generic
        // --from-env-file` turns Jwt__SigningKeyPem into a key, which mounts as a file of that
        // name, which the C# already reads as Jwt:SigningKeyPem.
        var dir = NewDir("underscores");
        File.WriteAllText(Path.Combine(dir, "Jwt__SigningKeyPem"), "test-not-a-real-key");
        File.WriteAllText(Path.Combine(dir, "Store__InternalApiKey"), "test-not-a-real-key");

        var builder = new ConfigurationBuilder();
        var names = builder.AddFileSecrets(dir);
        var config = builder.Build();

        Assert.Equal(UnderscoreNames, names);
        Assert.Equal("test-not-a-real-key", config["Jwt:SigningKeyPem"]);
        Assert.Equal("test-not-a-real-key", config["Store:InternalApiKey"]);
    }

    [Fact]
    public void AKubernetesSymlinkFarmYieldsTheKeysAndNoneOfTheMachinery()
    {
        // A projected secret volume is not a flat directory of files. Kubernetes writes the bytes
        // into a timestamped directory, points `..data` at it, and makes every key a symlink to
        // `..data/<key>`. An atomic rotation leaves a second timestamped directory behind while it
        // swaps. If any of that leaked through as a configuration key, the API would carry a
        // setting called "..data" whose value is a directory.
        var dir = NewDir("projected");
        var payload = Path.Combine(dir, "..2026_08_24_09_11_02.123456789");
        Directory.CreateDirectory(payload);
        File.WriteAllText(Path.Combine(payload, "MAILJET_API_KEY"), "test-not-a-real-key");
        File.WriteAllText(Path.Combine(payload, "Jwt__SigningKeyPem"), "test-not-a-real-key");

        Directory.CreateSymbolicLink(Path.Combine(dir, "..data"), payload);
        File.CreateSymbolicLink(Path.Combine(dir, "MAILJET_API_KEY"), Path.Combine(payload, "MAILJET_API_KEY"));
        File.CreateSymbolicLink(Path.Combine(dir, "Jwt__SigningKeyPem"), Path.Combine(payload, "Jwt__SigningKeyPem"));

        var builder = new ConfigurationBuilder();
        var names = builder.AddFileSecrets(dir);
        var config = builder.Build();

        Assert.Equal(ProjectedNames, names);
        Assert.Equal("test-not-a-real-key", config["MAILJET_API_KEY"]);
        Assert.Equal("test-not-a-real-key", config["Jwt:SigningKeyPem"]);
        Assert.Null(config["..data"]);
    }

    [Fact]
    public void ATrailingNewlineIsNotPartOfTheSecret()
    {
        // `printf '%s'` and kubectl's --from-env-file write the exact bytes; `echo > file` appends
        // a newline that is not part of the credential. A signing key carrying a stray \n fails as
        // an invalid-signature error nowhere near the mount. prospector/file_secrets.py strips
        // exactly one trailing newline and never more, so a value whose real content ends in a
        // space survives. This asserts what KeyPerFile actually does, so the two ends of the estate
        // cannot disagree silently.
        var dir = NewDir("newline");
        File.WriteAllText(Path.Combine(dir, "WITH_NEWLINE"), "test-value\n");
        File.WriteAllText(Path.Combine(dir, "WITHOUT_NEWLINE"), "test-value");

        var builder = new ConfigurationBuilder();
        builder.AddFileSecrets(dir);
        var config = builder.Build();

        Assert.Equal("test-value", config["WITH_NEWLINE"]);
        Assert.Equal("test-value", config["WITHOUT_NEWLINE"]);
    }

    [Fact]
    public void TheMountedFileBeatsAnEnvironmentVariableOfTheSameName()
    {
        // Both can be set on a box that has a .env and a mount. The file is what the cluster
        // deployed and what a rotation updates; the environment variable is the stale copy.
        // Preferring the environment would mean a rotated credential silently does not take
        // effect, which is the hardest version of this failure to see.
        var dir = NewDir("precedence");
        File.WriteAllText(Path.Combine(dir, "Store__InternalApiKey"), "from-the-mount");

        var builder = new ConfigurationBuilder();
        builder.AddInMemoryCollection(new Dictionary<string, string?>(StringComparer.Ordinal)
        {
            ["Store:InternalApiKey"] = "from-the-environment",
        });
        builder.AddFileSecrets(dir);
        var config = builder.Build();

        Assert.Equal("from-the-mount", config["Store:InternalApiKey"]);
    }
}
