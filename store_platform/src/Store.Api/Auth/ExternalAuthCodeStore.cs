using System.Security.Cryptography;
using Microsoft.Extensions.Caching.Memory;
using Store.Api.Identity;

namespace Store.Api.Auth;

/// <summary>
/// Short-lived, single-use handoff codes for the social-login redirect (E16 D1). The provider
/// redirect lands on the API; the API mints the real tokens, stashes the <see cref="AuthResponseDto"/>
/// here under an opaque code, and 302s the browser to the web with only that code in the URL. The
/// web immediately POSTs the code to <c>/v1/auth/external/exchange</c> to get the tokens in a
/// response body — so JWT/refresh never touch the URL, browser history, server logs, or localStorage.
/// </summary>
public interface IExternalAuthCodeStore
{
    /// <summary>Stash an auth result and return the opaque, URL-safe lookup code.</summary>
    string Issue(AuthResponseDto auth);

    /// <summary>Atomically fetch-and-remove the result for a code; null if unknown, expired, or already used.</summary>
    AuthResponseDto? Consume(string code);

    /// <summary>
    /// Mint a short-lived single-use ticket binding the CURRENT user to an about-to-start provider
    /// link (E16 D9). Lets an authenticated bearer POST hand the user identity to a subsequent
    /// full-page nav (which can't carry the bearer) without putting the user id in the URL.
    /// </summary>
    string IssueLinkTicket(Guid userId);

    /// <summary>Atomically fetch-and-remove the user id for a link ticket; null if unknown/expired/used.</summary>
    Guid? ConsumeLinkTicket(string ticket);
}

/// <summary>
/// <see cref="IMemoryCache"/>-backed implementation. Codes live 60 seconds and are removed on first
/// read (single-use). NOTE: in-memory means single-instance only — correct for beta. A multi-instance
/// deployment must back this with a shared store (Redis/DB); the refresh token itself is already
/// DB-persisted, so only this ~60s handoff is process-local.
/// </summary>
public sealed class ExternalAuthCodeStore : IExternalAuthCodeStore
{
    private static readonly TimeSpan Ttl = TimeSpan.FromSeconds(60);
    private readonly IMemoryCache _cache;

    public ExternalAuthCodeStore(IMemoryCache cache) => _cache = cache;

    public string Issue(AuthResponseDto auth)
    {
        var code = Base64UrlToken();
        _cache.Set(CacheKey(code), auth, Ttl);
        return code;
    }

    public AuthResponseDto? Consume(string code)
    {
        if (string.IsNullOrWhiteSpace(code)) return null;
        var key = CacheKey(code);
        if (_cache.TryGetValue(key, out AuthResponseDto? auth))
        {
            _cache.Remove(key); // single-use
            return auth;
        }
        return null;
    }

    public string IssueLinkTicket(Guid userId)
    {
        var ticket = Base64UrlToken();
        _cache.Set(TicketKey(ticket), userId, Ttl);
        return ticket;
    }

    public Guid? ConsumeLinkTicket(string ticket)
    {
        if (string.IsNullOrWhiteSpace(ticket)) return null;
        var key = TicketKey(ticket);
        if (_cache.TryGetValue(key, out Guid userId))
        {
            _cache.Remove(key); // single-use
            return userId;
        }
        return null;
    }

    private static string CacheKey(string code) => $"extauth:code:{code}";
    private static string TicketKey(string ticket) => $"extauth:link:{ticket}";

    private static string Base64UrlToken()
    {
        var bytes = RandomNumberGenerator.GetBytes(32);
        return Convert.ToBase64String(bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_');
    }
}
