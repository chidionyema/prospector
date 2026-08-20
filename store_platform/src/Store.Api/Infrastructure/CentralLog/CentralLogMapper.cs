using System.Globalization;
using System.Text.RegularExpressions;

namespace Store.Api.Infrastructure.CentralLog;

/// <summary>Turns a .NET log record into a <see cref="CentralLogLine"/>.</summary>
public static class CentralLogMapper
{
    private const int MaxMessage = 2000;
    private const int MaxValue = 512;
    private const int MaxEvent = 128;

    /// <summary>
    /// Field NAMES that must never travel. Matched on the name, not the value: a value scan
    /// cannot recognise a credential format it has not seen, and this cannot be fooled by a new
    /// provider's key shape. Redaction happens in the producer so the secret is never on the
    /// wire and never on the log volume.
    /// </summary>
    private static readonly Regex SecretName = new(
        "key|secret|token|password|passwd|credential|authorization|auth|cookie|session|pem|private",
        RegexOptions.IgnoreCase | RegexOptions.Compiled,
        TimeSpan.FromSeconds(1));

    private static readonly Regex EvtClean = new(
        "[^a-z0-9._-]+", RegexOptions.Compiled, TimeSpan.FromSeconds(1));

    /// <summary>
    /// Categories whose own records must not be shipped. Logging the shipper's HTTP failure
    /// through the shipper is a loop that fills the buffer with reports of the buffer filling.
    /// </summary>
    public static bool IsSelfReferential(string category) =>
        category.StartsWith("Store.Api.Infrastructure.CentralLog", StringComparison.Ordinal)
        || category.StartsWith("System.Net.Http", StringComparison.Ordinal);

    public static string Level(LogLevel level) => level switch
    {
        LogLevel.Trace or LogLevel.Debug => "debug",
        LogLevel.Information => "info",
        LogLevel.Warning => "warn",
        LogLevel.Error => "error",
        LogLevel.Critical => "crit",
        _ => "info",
    };

    /// <summary>
    /// A stable machine name, never the interpolated message. An <c>EventId.Name</c> is used
    /// when the caller supplied one; otherwise the category, which is stable by construction.
    /// Using the formatted message would give a different <c>evt</c> per order id and make the
    /// field useless for counting, which is the only reason it is separate from <c>msg</c>.
    /// </summary>
    public static string Event(string category, EventId eventId)
    {
        var raw = string.IsNullOrWhiteSpace(eventId.Name) ? $"log.{category}" : eventId.Name!;
        var cleaned = EvtClean.Replace(raw.Trim().ToLowerInvariant(), ".").Trim('.');
        if (cleaned.Length == 0) cleaned = "log.unnamed";
        return Truncate(cleaned, MaxEvent)!;
    }

    public static string Timestamp(DateTimeOffset when) =>
        when.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ", CultureInfo.InvariantCulture);

    private static string? Truncate(string? value, int max)
    {
        if (string.IsNullOrEmpty(value)) return null;
        return value.Length > max ? value[..max] : value;
    }

    public static CentralLogLine Map(
        string svc,
        string category,
        LogLevel level,
        EventId eventId,
        string message,
        Exception? exception,
        IReadOnlyList<KeyValuePair<string, object?>>? state,
        string? corr,
        DateTimeOffset when)
    {
        Dictionary<string, string>? ctx = null;
        void Put(string name, string value)
        {
            ctx ??= new Dictionary<string, string>(StringComparer.Ordinal);
            ctx[name] = SecretName.IsMatch(name) ? "[redacted]" : value;
        }

        if (state is not null)
        {
            foreach (var pair in state)
            {
                // `{OriginalFormat}` is the un-interpolated template. It is already the basis of
                // `evt` and repeating it in ctx doubles the size of every line for nothing.
                if (string.Equals(pair.Key, "{OriginalFormat}", StringComparison.Ordinal)) continue;
                var value = Truncate(pair.Value?.ToString(), MaxValue);
                if (value is null) continue;
                Put(pair.Key, value);
            }
        }

        if (exception is not null)
        {
            Put("exc", exception.GetType().Name);
            Put("exc_msg", Truncate(exception.Message, MaxValue) ?? "");
        }

        return new CentralLogLine
        {
            Ts = Timestamp(when),
            Svc = svc,
            Lvl = Level(level),
            Evt = Event(category, eventId),
            Msg = Truncate(message, MaxMessage),
            Corr = string.IsNullOrWhiteSpace(corr) ? null : corr,
            Ctx = ctx,
        };
    }
}
