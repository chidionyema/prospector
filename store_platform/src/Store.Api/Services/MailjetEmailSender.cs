using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;

namespace Store.Api.Services;

/// <summary>
/// Sends the magic-link email via Mailjet's v3.1 send API. Unconfigured (missing key, secret, or
/// from-address) → <see cref="IsConfigured"/> false and sends are skipped. A failed send is
/// non-fatal: the entitlement already exists and the link can be re-issued from the success page.
///
/// Why Mailjet rather than Postmark (founder's call, 2026-07-30): the DNS shape is identical
/// either way — both authenticate a sending domain with TXT records only (SPF + DKIM, no MX),
/// which is what mumchimp.com requires, because its MX (<c>5 smtp.google.com</c>) must keep
/// serving support@ and cannot be repointed. The records are <c>include:spf.mailjet.com</c> in
/// the apex SPF and a DKIM key at <c>mailjet._domainkey</c> (selector confirmed against the
/// live records on theintroexchange.com, which has run Mailjet in production since 2026-06-12).
///
/// Three behaviours here are deliberate:
/// (1) Mailjet authenticates with a key PAIR over HTTP Basic — the public API key as the
///     username, the private secret as the password. A half-configured pair reads as
///     unconfigured rather than being attempted, so a 401 storm cannot masquerade as an outage.
/// (2) This sender NEVER throws. A provider failure returns false, which the webhook already
///     handles by logging FULFILMENT-EMAIL-FAILED with the order URL for manual re-issue.
///     Letting HttpRequestException escape would take the Stripe webhook handler down with it
///     on a transient DNS/TLS blip — after the money was captured and the entitlement written.
/// (3) The pack title is HTML-encoded into the HTML part. Titles come from our own catalogue,
///     but an unescaped ampersand alone is enough to produce a malformed email body.
/// </summary>
public sealed class MailjetEmailSender : IEmailSender
{
    private const string SendPath = "/v3.1/send";

    // Mailjet's v3.1 API is PascalCase. This MUST be set explicitly: JsonContent.Create with no
    // options serializes with JsonSerializerDefaults.Web — i.e. camelCase — so the envelope would
    // go out as {"messages":[{"from":…,"htmlPart":…}]} and Mailjet would reject it. The sender
    // this replaced carried a comment claiming PascalCase was the default; it is not.
    private static readonly JsonSerializerOptions PascalCase = new() { PropertyNamingPolicy = null };

    private readonly HttpClient _http;
    private readonly ILogger<MailjetEmailSender> _logger;
    private readonly string? _apiKey;
    private readonly string? _apiSecret;
    private readonly string _fromEmail;

    public bool IsConfigured =>
        !string.IsNullOrEmpty(_apiKey)
        && !string.IsNullOrEmpty(_apiSecret)
        && !string.IsNullOrEmpty(_fromEmail);

    public MailjetEmailSender(HttpClient http, IConfiguration config, ILogger<MailjetEmailSender> logger)
    {
        ArgumentNullException.ThrowIfNull(http);
        ArgumentNullException.ThrowIfNull(config);
        ArgumentNullException.ThrowIfNull(logger);

        _http = http;
        _logger = logger;
        _apiKey = config["Mailjet:ApiKey"] ?? Environment.GetEnvironmentVariable("MAILJET_API_KEY");
        _apiSecret = config["Mailjet:ApiSecret"] ?? Environment.GetEnvironmentVariable("MAILJET_API_SECRET");
        _fromEmail = config["Mailjet:FromEmail"] ?? Environment.GetEnvironmentVariable("MAILJET_FROM_EMAIL") ?? "";
        _http.BaseAddress ??= new Uri("https://api.mailjet.com");
    }

    public async Task<bool> SendDownloadLinkAsync(string toEmail, string packTitle, string orderUrl)
    {
        ArgumentException.ThrowIfNullOrEmpty(toEmail);
        if (!IsConfigured)
        {
            return false;
        }

        var safeTitle = System.Net.WebUtility.HtmlEncode(packTitle);
        var envelope = new MailjetEnvelope(
        [
            new MailjetMessage(
                From: new MailjetAddress(_fromEmail),
                To: [new MailjetAddress(toEmail)],
                Subject: $"Your purchase: {packTitle}",
                HTMLPart:
                    $"<p>Thank you for your purchase of <strong>{safeTitle}</strong>.</p>" +
                    $"<p><a href=\"{orderUrl}\">Access your download here</a>.</p>" +
                    "<p>This link is tied to your purchase — please keep it private.</p>",
                TextPart:
                    $"Thank you for your purchase of {packTitle}.\nAccess your download: {orderUrl}\n" +
                    "This link is tied to your purchase — please keep it private."),
        ]);

        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Post, SendPath)
            {
                Content = JsonContent.Create(envelope, options: PascalCase),
            };
            var basic = Convert.ToBase64String(Encoding.ASCII.GetBytes($"{_apiKey}:{_apiSecret}"));
            request.Headers.Authorization = new AuthenticationHeaderValue("Basic", basic);

            using var response = await _http.SendAsync(request).ConfigureAwait(false);
            if (response.IsSuccessStatusCode)
            {
                return true;
            }

            // The body carries Mailjet's reason (unverified sender, suppressed recipient, bad
            // key). Without it the operator only sees a status code and cannot act.
            var detail = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
            _logger.LogError(
                "Mailjet send failed ({Status}) to {Email}: {Detail}",
                (int)response.StatusCode, toEmail, detail);
            return false;
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Mailjet send threw for {Email}", toEmail);
            return false;
        }
    }

    // Mailjet expects PascalCase JSON, which is System.Text.Json's default. Nested so these
    // don't collide with the one-public-type-per-file convention.
    private sealed record MailjetEnvelope(MailjetMessage[] Messages);

    private sealed record MailjetMessage(
        MailjetAddress From,
        MailjetAddress[] To,
        string Subject,
        string HTMLPart,
        string TextPart);

    private sealed record MailjetAddress(string Email);
}
