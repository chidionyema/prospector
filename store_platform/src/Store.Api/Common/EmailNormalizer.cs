using System.Text.RegularExpressions;

namespace Store.Api.Common;

public static class EmailNormalizer
{
    /// <summary>
    /// Normalizes an email address for anti-Sybil checks (lowercased, dotless/plus-stripped for known providers).
    /// </summary>
    public static string Normalize(string email)
    {
        if (string.IsNullOrWhiteSpace(email)) return string.Empty;

        var parts = email.ToLowerInvariant().Split('@');
        if (parts.Length != 2) return email.ToLowerInvariant();

        var local = parts[0];
        var domain = parts[1];

        // For gmail.com and googlemail.com, strip dots and everything after '+'
        if (string.Equals(domain, "gmail.com", StringComparison.Ordinal) || string.Equals(domain, "googlemail.com", StringComparison.Ordinal))
        {
            local = local.Split('+')[0].Replace(".", "", StringComparison.Ordinal);
            domain = "gmail.com";
        }
        // Add other providers as needed, or a generic plus-strip
        else
        {
            local = local.Split('+')[0];
        }

        return $"{local}@{domain}";
    }
}
