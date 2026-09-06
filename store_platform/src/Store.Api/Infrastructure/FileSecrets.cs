using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.FileProviders;

namespace Store.Api.Infrastructure;

/// <summary>
/// Read the API's secrets from a mounted directory, one file per setting.
///
/// WHY THIS EXISTS. <c>secrets-not-from-env-vars</c>, one of the 26 admission policies in
/// <c>deploy/k8s/policies</c>, refuses <c>envFrom.secretRef</c> and
/// <c>env[].valueFrom.secretKeyRef</c> outright. A pod spec that puts a credential in the
/// container environment is refused at admission, so the cluster hands secrets over as files or
/// not at all. <c>deploy/compose/docker-compose.yml</c> supplies all seven of this API's secrets
/// through <c>environment:</c> today, which is exactly the shape the policy refuses.
///
/// The engine solved the same problem on 2026-08-24 in <c>prospector/file_secrets.py</c>. This is
/// the same contract for the API, and it deliberately reads the same environment variable,
/// <c>PROSPECTOR_SECRETS_DIR</c>, so there is one name across the estate rather than one per
/// workload.
///
/// NOTHING WAS HAND-ROLLED. The reading is done by
/// <c>Microsoft.Extensions.Configuration.KeyPerFile</c>, which ships inside the
/// <c>Microsoft.AspNetCore.App</c> shared framework — no package reference was added. It already
/// maps a file named <c>Jwt__SigningKeyPem</c> onto the configuration key
/// <c>Jwt:SigningKeyPem</c>, which is the naming the compose file and the .NET code already use.
/// What is added here is only the part the framework has no opinion about: refusing to start when
/// the mount is missing or empty.
///
/// WHY REFUSE RATHER THAN CARRY ON. <c>optional: true</c> on a secrets source is the 2026-08-24
/// incident written as a setting: a box came up carrying none of its 24 settings and the deploy
/// script reported success. The API's own gates then failed hours later and somewhere else. A
/// missing mount is a deployment error, and the cheapest place to read it is the container that
/// will not start.
///
/// NO VALUE IS READ, LOGGED OR THROWN HERE. LAW 21: naming a secret is fine, printing it is not.
/// This class touches file NAMES and paths only; the bytes are read by the framework provider and
/// go straight into configuration.
/// </summary>
public static class FileSecrets
{
    /// <summary>The variable that opts a process in. Unset on every laptop, test run and CI job.</summary>
    public const string DirectoryVariable = "PROSPECTOR_SECRETS_DIR";

    /// <summary>
    /// Kubernetes builds a projected secret volume as a symlink farm: the real bytes live in a
    /// timestamped <c>..2026_08_24_09_11_02.123456789</c> directory, <c>..data</c> is a symlink to
    /// the current one, and each key is a symlink to <c>..data/&lt;key&gt;</c>. The key symlinks
    /// resolve to regular files and read normally. The <c>..</c>-prefixed entries are the
    /// machinery, not keys, and an atomic rotation leaves a second one behind mid-update.
    /// </summary>
    private const string KubernetesInternalPrefix = "..";

    /// <summary>
    /// Add the mounted secrets directory as a configuration source, if one was named.
    /// Returns the file names that were found, sorted — never a value.
    /// </summary>
    /// <remarks>
    /// The source is added LAST, so a mounted file beats an environment variable of the same name.
    /// Both can be set on a laptop that has a <c>.env</c> and a mount. The file is what the cluster
    /// deployed and what a rotation updates; the environment variable is the stale copy, and
    /// preferring it would mean a rotated secret silently does not take effect.
    /// </remarks>
    /// <exception cref="InvalidOperationException">
    /// The variable is set and the directory is missing, or holds no usable key file.
    /// </exception>
    public static IReadOnlyList<string> AddFileSecrets(this IConfigurationBuilder builder, string? directory = null)
    {
        ArgumentNullException.ThrowIfNull(builder);

        var path = (directory ?? Environment.GetEnvironmentVariable(DirectoryVariable) ?? string.Empty).Trim();
        if (path.Length == 0)
        {
            return Array.Empty<string>();
        }

        if (!Directory.Exists(path))
        {
            throw new InvalidOperationException(
                $"{DirectoryVariable}={path} but that is not a directory. Nothing was loaded, so every " +
                "credential this API needs is missing. Either the Secret is not mounted or the mountPath " +
                "and the variable disagree - deploy/k8s/base/api.yaml sets both.");
        }

        var names = Directory.EnumerateFiles(path)
            .Select(Path.GetFileName)
            .Where(name => name is not null && !name.StartsWith(KubernetesInternalPrefix, StringComparison.Ordinal))
            .Select(name => name!)
            .OrderBy(name => name, StringComparer.Ordinal)
            .ToArray();

        if (names.Length == 0)
        {
            throw new InvalidOperationException(
                $"{DirectoryVariable}={path} is an empty directory. A mount that exists and holds nothing " +
                "is the shape a misnamed Secret takes, and it is indistinguishable from success to " +
                "everything downstream.");
        }

        var fullPath = Path.GetFullPath(path);
        builder.AddKeyPerFile(source =>
        {
            source.FileProvider = new PhysicalFileProvider(fullPath);
            source.Optional = false;
            source.ReloadOnChange = false;
            // The framework default ignores names beginning with "ignore.". The estate's mounts
            // carry Kubernetes' own ".."-prefixed machinery instead, and nothing guarantees that a
            // symlink pointing at a directory is excluded on every runtime. Naming the condition
            // here makes the skip a decision rather than a side effect.
            source.IgnoreCondition = file =>
                Path.GetFileName(file).StartsWith(KubernetesInternalPrefix, StringComparison.Ordinal);
        });

        return names;
    }
}
