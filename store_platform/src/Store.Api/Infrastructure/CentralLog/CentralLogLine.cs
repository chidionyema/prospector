using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Store.Api.Infrastructure.CentralLog;

/// <summary>
/// One line of the estate-wide log format, exactly as <c>docs/LOGGING_AND_RETENTION.md</c>
/// §4.4 declares it. The engine's ingest parses this same shape from every service.
///
/// <para><c>host</c> is deliberately absent. The ingest sets it from the connection, because a
/// service that names its own host can claim to be a different one.</para>
/// </summary>
public sealed class CentralLogLine
{
    [JsonPropertyName("ts")] public string Ts { get; init; } = "";
    [JsonPropertyName("svc")] public string Svc { get; init; } = "";
    [JsonPropertyName("lvl")] public string Lvl { get; init; } = "info";
    [JsonPropertyName("evt")] public string Evt { get; init; } = "";

    [JsonPropertyName("msg")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Msg { get; init; }

    [JsonPropertyName("corr")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Corr { get; init; }

    [JsonPropertyName("ctx")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public IReadOnlyDictionary<string, string>? Ctx { get; init; }

    private static readonly JsonSerializerOptions Json = new()
    {
        // One line per record, so a newline inside the payload would split one line into two
        // and corrupt the file for everything downstream.
        WriteIndented = false,
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };

    public string ToNdjson() => JsonSerializer.Serialize(this, Json).ReplaceLineEndings("");
}
