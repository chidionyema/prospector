using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging.Abstractions;
using Store.Api.Services;
using Xunit;

namespace Store.Tests.Services;

/// <summary>
/// Proves the fulfilment-email path after the move off Postmark: the Mailjet v3.1 envelope is
/// shaped the way Mailjet parses it (PascalCase, Messages[], Basic auth over a key PAIR), a
/// half-configured key pair reads as unconfigured rather than being attempted, and — the one
/// that protects money already taken — a provider failure returns false instead of throwing out
/// of the Stripe webhook handler.
///
/// Offline: every send goes through a stub HttpMessageHandler, no Mailjet account required.
///
/// Config values are set to the empty string rather than omitted, so the sender's
/// <c>config[...] ?? Environment.GetEnvironmentVariable(...)</c> fallback cannot reach a real
/// MAILJET_* variable on a developer's machine and turn an "unconfigured" test green-or-red by
/// accident.
/// </summary>
public sealed class MailjetEmailSenderTests
{
    private const string Key = "public-key-abc";
    private const string Secret = "private-secret-xyz";
    private const string From = "orders@mumchimp.com";
    private const string Buyer = "buyer@example.com";

    // ---- configuration gating ----------------------------------------------------------------

    [Fact]
    public void Unconfigured_when_nothing_is_set()
    {
        var sender = Build(new StubHandler(), key: "", secret: "", from: "");

        Assert.False(sender.IsConfigured);
    }

    [Fact]
    public void Unconfigured_when_the_key_has_no_secret()
    {
        // Mailjet authenticates with a PAIR. A key on its own yields 401 on every send, which
        // looks like a provider outage rather than a config mistake — so it must read as
        // unconfigured and be reported by the boot-time DELIVERY-DEGRADED gate instead.
        var sender = Build(new StubHandler(), key: Key, secret: "", from: From);

        Assert.False(sender.IsConfigured);
    }

    [Fact]
    public void Unconfigured_when_the_from_address_is_missing()
    {
        var sender = Build(new StubHandler(), key: Key, secret: Secret, from: "");

        Assert.False(sender.IsConfigured);
    }

    [Fact]
    public async Task Unconfigured_send_returns_false_without_calling_Mailjet()
    {
        var handler = new StubHandler();
        var sender = Build(handler, key: "", secret: "", from: "");

        var sent = await sender.SendDownloadLinkAsync(Buyer, "Pack", "https://s/orders/t");

        Assert.False(sent);
        Assert.Equal(0, handler.Calls);
    }

    // ---- the wire format ---------------------------------------------------------------------

    [Fact]
    public async Task Send_posts_a_v3_1_envelope_with_basic_auth_over_the_key_pair()
    {
        var handler = new StubHandler();
        var sender = Build(handler, key: Key, secret: Secret, from: From);

        var sent = await sender.SendDownloadLinkAsync(Buyer, "Cold Email Pack", "https://store/orders/tok123");

        Assert.True(sent);
        Assert.Equal(1, handler.Calls);
        Assert.Equal(HttpMethod.Post, handler.LastMethod);
        Assert.Equal("https://api.mailjet.com/v3.1/send", handler.LastUri?.ToString());

        // Basic auth, not a bearer token: username = public key, password = private secret.
        Assert.Equal("Basic", handler.LastAuthScheme);
        var decoded = Encoding.ASCII.GetString(Convert.FromBase64String(handler.LastAuthParameter!));
        Assert.Equal($"{Key}:{Secret}", decoded);

        // Mailjet parses PascalCase only; a camelCase envelope is accepted with a 400.
        using var doc = JsonDocument.Parse(handler.LastBody!);
        var message = doc.RootElement.GetProperty("Messages")[0];
        Assert.Equal(From, message.GetProperty("From").GetProperty("Email").GetString());
        Assert.Equal(Buyer, message.GetProperty("To")[0].GetProperty("Email").GetString());
        Assert.Equal("Your purchase: Cold Email Pack", message.GetProperty("Subject").GetString());
        Assert.Contains("https://store/orders/tok123", message.GetProperty("HTMLPart").GetString(), StringComparison.Ordinal);
        Assert.Contains("https://store/orders/tok123", message.GetProperty("TextPart").GetString(), StringComparison.Ordinal);
    }

    [Fact]
    public async Task Send_html_encodes_the_pack_title()
    {
        var handler = new StubHandler();
        var sender = Build(handler, key: Key, secret: Secret, from: From);

        await sender.SendDownloadLinkAsync(Buyer, "Sales & Ops <Pack>", "https://store/orders/t");

        using var doc = JsonDocument.Parse(handler.LastBody!);
        var message = doc.RootElement.GetProperty("Messages")[0];
        var html = message.GetProperty("HTMLPart").GetString()!;

        Assert.Contains("Sales &amp; Ops &lt;Pack&gt;", html, StringComparison.Ordinal);
        Assert.DoesNotContain("<Pack>", html, StringComparison.Ordinal);

        // The plain-text part must NOT be encoded — buyers would read the entities literally.
        Assert.Contains("Sales & Ops <Pack>", message.GetProperty("TextPart").GetString(), StringComparison.Ordinal);
    }

    // ---- failure handling --------------------------------------------------------------------

    [Fact]
    public async Task Send_returns_false_on_a_provider_error_status()
    {
        var handler = new StubHandler { Status = HttpStatusCode.Forbidden, Body = "{\"ErrorMessage\":\"unverified sender\"}" };
        var sender = Build(handler, key: Key, secret: Secret, from: From);

        var sent = await sender.SendDownloadLinkAsync(Buyer, "Pack", "https://s/orders/t");

        Assert.False(sent);
    }

    [Fact]
    public async Task Send_returns_false_instead_of_throwing_when_the_transport_fails()
    {
        // This is the one that matters for money: the caller is inside the Stripe webhook,
        // after the charge is captured and the entitlement is written. An escaping
        // HttpRequestException would fail the webhook response rather than logging
        // FULFILMENT-EMAIL-FAILED with the order URL for manual re-issue.
        var handler = new StubHandler { Throw = new HttpRequestException("no such host") };
        var sender = Build(handler, key: Key, secret: Secret, from: From);

        var sent = await sender.SendDownloadLinkAsync(Buyer, "Pack", "https://s/orders/t");

        Assert.False(sent);
    }

    // ---- helpers -----------------------------------------------------------------------------

    private static MailjetEmailSender Build(StubHandler handler, string key, string secret, string from)
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>(StringComparer.Ordinal)
            {
                ["Mailjet:ApiKey"] = key,
                ["Mailjet:ApiSecret"] = secret,
                ["Mailjet:FromEmail"] = from,
            })
            .Build();

        return new MailjetEmailSender(new HttpClient(handler), config, NullLogger<MailjetEmailSender>.Instance);
    }

    private sealed class StubHandler : HttpMessageHandler
    {
        public int Calls { get; private set; }

        public HttpStatusCode Status { get; init; } = HttpStatusCode.OK;

        public string Body { get; init; } = "{\"Messages\":[{\"Status\":\"success\",\"To\":[{\"MessageUUID\":\"uuid-1\"}]}]}";

        public Exception? Throw { get; init; }

        public HttpMethod? LastMethod { get; private set; }

        public Uri? LastUri { get; private set; }

        public string? LastAuthScheme { get; private set; }

        public string? LastAuthParameter { get; private set; }

        public string? LastBody { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Calls++;
            LastMethod = request.Method;
            LastUri = request.RequestUri;
            LastAuthScheme = request.Headers.Authorization?.Scheme;
            LastAuthParameter = request.Headers.Authorization?.Parameter;
            LastBody = request.Content is null
                ? null
                : await request.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);

            if (Throw is not null)
            {
                throw Throw;
            }

            return new HttpResponseMessage(Status) { Content = new StringContent(Body) };
        }
    }
}
