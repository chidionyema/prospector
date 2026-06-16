using System.Net.Http.Json;

namespace Store.Api.Services;

/// <summary>
/// Sends the magic-link email via Postmark's transactional API. Unconfigured (no server
/// token / from-address) → IsConfigured false and sends are skipped. A failed send is
/// non-fatal: the entitlement already exists and the link can be re-issued.
/// </summary>
public sealed class PostmarkEmailSender : IEmailSender
{
    private readonly HttpClient _http;
    private readonly string? _token;
    private readonly string _fromEmail;

    public bool IsConfigured => !string.IsNullOrEmpty(_token) && !string.IsNullOrEmpty(_fromEmail);

    public PostmarkEmailSender(HttpClient http, IConfiguration config)
    {
        ArgumentNullException.ThrowIfNull(http);
        ArgumentNullException.ThrowIfNull(config);

        _http = http;
        _token = config["Postmark:ServerToken"] ?? Environment.GetEnvironmentVariable("POSTMARK_SERVER_TOKEN");
        _fromEmail = config["Postmark:FromEmail"] ?? Environment.GetEnvironmentVariable("POSTMARK_FROM_EMAIL") ?? "";
        _http.BaseAddress ??= new Uri("https://api.postmarkapp.com");
    }

    public async Task<bool> SendDownloadLinkAsync(string toEmail, string packTitle, string orderUrl)
    {
        ArgumentException.ThrowIfNullOrEmpty(toEmail);
        if (!IsConfigured)
        {
            return false;
        }

        var message = new PostmarkMessage(
            From: _fromEmail,
            To: toEmail,
            Subject: $"Your purchase: {packTitle}",
            HtmlBody:
                $"<p>Thank you for your purchase of <strong>{packTitle}</strong>.</p>" +
                $"<p><a href=\"{orderUrl}\">Access your download here</a>.</p>" +
                "<p>This link is tied to your purchase — please keep it private.</p>",
            TextBody:
                $"Thank you for your purchase of {packTitle}.\nAccess your download: {orderUrl}\n" +
                "This link is tied to your purchase — please keep it private.",
            MessageStream: "outbound");

        using var request = new HttpRequestMessage(HttpMethod.Post, "/email")
        {
            Content = JsonContent.Create(message),
        };
        request.Headers.Add("X-Postmark-Server-Token", _token);

        using var response = await _http.SendAsync(request).ConfigureAwait(false);
        return response.IsSuccessStatusCode;
    }

    // Postmark expects PascalCase JSON, which is System.Text.Json's default. Nested so it
    // doesn't collide with the one-public-type-per-file convention.
    private sealed record PostmarkMessage(
        string From,
        string To,
        string Subject,
        string HtmlBody,
        string TextBody,
        string MessageStream);
}
