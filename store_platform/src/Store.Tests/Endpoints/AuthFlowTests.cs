using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.AspNetCore.Identity;
using Microsoft.Extensions.DependencyInjection;
using Store.Catalog.Domain.Identity;

namespace Store.Tests.Endpoints;

/// <summary>
/// The customer-account loop, ported from the-introduction-exchange: register, verify, log in,
/// read your own profile.
/// </summary>
/// <remarks>
/// The fence these tests exist for is email verification. Orders are joined to an account by email
/// STRING — there is no UserId column on an order — so the only thing standing between a customer's
/// purchase history and anyone who can type their address is <c>EmailConfirmed</c>. A regression
/// that let an unverified account log in would not look like a bug; it would look like a
/// convenience, and it would expose one customer's orders to another.
///
/// The verification token is minted here through the app's OWN UserManager, resolved from the test
/// host's service provider. That matters: the token is protected by ASP.NET DataProtection, so a
/// token minted by any other process would fail to unprotect for reasons unrelated to the endpoint.
/// Reaching into the host is what makes the round-trip a genuine test of /verify-email.
/// </remarks>
public sealed class AuthFlowTests : IClassFixture<StoreApiFactory>
{
    private readonly StoreApiFactory _factory;

    public AuthFlowTests(StoreApiFactory factory) => _factory = factory;

    private static object Registration(string user, string email) => new
    {
        username = user,
        email,
        password = "correct-horse-8",
        tos_version = "2026-07-31",
    };

    private async Task<(string UserId, string Token)> ConfirmationTokenAsync(string email)
    {
        using var scope = _factory.Services.CreateScope();
        var users = scope.ServiceProvider.GetRequiredService<UserManager<StoreUser>>();
        var user = await users.FindByEmailAsync(email);
        Assert.NotNull(user);
        return (user!.Id.ToString(), await users.GenerateEmailConfirmationTokenAsync(user));
    }

    [Fact]
    public async Task Registration_issues_no_token_until_the_address_is_verified()
    {
        var client = _factory.CreateClient();

        var registered = await client.PostAsJsonAsync("/v1/auth/register", Registration("gatecheck", "gatecheck@example.com"));
        Assert.Equal(HttpStatusCode.OK, registered.StatusCode);

        var body = await registered.Content.ReadFromJsonAsync<JsonElement>();
        Assert.Equal(string.Empty, body.GetProperty("token").GetString());

        // Same credentials, before verification: refused.
        var early = await client.PostAsJsonAsync("/v1/auth/login", new { username = "gatecheck", password = "correct-horse-8" });
        Assert.Equal(HttpStatusCode.Unauthorized, early.StatusCode);
    }

    [Fact]
    public async Task A_verified_account_can_log_in_and_read_its_own_profile()
    {
        var client = _factory.CreateClient();
        await client.PostAsJsonAsync("/v1/auth/register", Registration("verified", "verified@example.com"));

        var (userId, token) = await ConfirmationTokenAsync("verified@example.com");
        var verified = await client.PostAsJsonAsync("/v1/auth/verify-email", new { user_id = userId, token });
        Assert.Equal(HttpStatusCode.OK, verified.StatusCode);

        var login = await client.PostAsJsonAsync("/v1/auth/login", new { username = "verified", password = "correct-horse-8" });
        Assert.Equal(HttpStatusCode.OK, login.StatusCode);
        var jwt = (await login.Content.ReadFromJsonAsync<JsonElement>()).GetProperty("token").GetString();
        Assert.False(string.IsNullOrWhiteSpace(jwt));

        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", jwt);
        var me = await client.GetFromJsonAsync<JsonElement>("/v1/auth/me");
        Assert.Equal("verified@example.com", me.GetProperty("email").GetString());
        Assert.True(me.GetProperty("email_confirmed").GetBoolean());
    }

    [Fact]
    public async Task A_bad_verification_token_is_refused()
    {
        var client = _factory.CreateClient();
        await client.PostAsJsonAsync("/v1/auth/register", Registration("badtoken", "badtoken@example.com"));

        var (userId, token) = await ConfirmationTokenAsync("badtoken@example.com");
        var tampered = await client.PostAsJsonAsync("/v1/auth/verify-email", new { user_id = userId, token = token + "x" });
        Assert.NotEqual(HttpStatusCode.OK, tampered.StatusCode);

        // And the account is still unverified, so the tamper bought nothing.
        var login = await client.PostAsJsonAsync("/v1/auth/login", new { username = "badtoken", password = "correct-horse-8" });
        Assert.Equal(HttpStatusCode.Unauthorized, login.StatusCode);
    }

    [Fact]
    public async Task Protected_endpoints_answer_401_rather_than_redirecting_to_a_login_page()
    {
        // AddIdentity defaults the challenge scheme to a cookie, which answers an unauthenticated
        // request with a 302 to /Account/Login — a page that does not exist in an API. The frontend
        // needs a 401 it can act on, so AddStoreAuth overrides the default scheme to JWT bearer.
        // This test fails if that override is ever dropped.
        var response = await _factory.CreateClient().GetAsync("/v1/auth/me");
        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task A_second_account_cannot_claim_an_address_that_is_already_registered()
    {
        var client = _factory.CreateClient();
        await client.PostAsJsonAsync("/v1/auth/register", Registration("firstclaim", "contested@example.com"));

        // Different username, same address. It must fail: order history is joined by email, so two
        // accounts on one address would each be shown the other's purchases.
        var second = await client.PostAsJsonAsync("/v1/auth/register", Registration("secondclaim", "contested@example.com"));
        Assert.NotEqual(HttpStatusCode.OK, second.StatusCode);
    }

    [Fact]
    public async Task The_httpOnly_cookie_alone_authenticates_a_request()
    {
        // The storefront keeps NO token in JavaScript. Login sets an HttpOnly "jwt" cookie
        // (JwtTokenService.cs:128) and every later call carries only that cookie — which works
        // solely because of the OnMessageReceived hook in AddStoreAuth. Before that hook the
        // cookie was set and never read, so this request would 401 while a bearer request passed,
        // and the whole no-token-in-JS design would silently be a fiction.
        var client = _factory.CreateClient();
        await client.PostAsJsonAsync("/v1/auth/register", Registration("cookieonly", "cookieonly@example.com"));
        var (userId, token) = await ConfirmationTokenAsync("cookieonly@example.com");
        await client.PostAsJsonAsync("/v1/auth/verify-email", new { user_id = userId, token });

        var login = await client.PostAsJsonAsync("/v1/auth/login", new { username = "cookieonly", password = "correct-horse-8" });
        Assert.Equal(HttpStatusCode.OK, login.StatusCode);
        Assert.Contains(login.Headers.GetValues("Set-Cookie"), c => c.StartsWith("jwt=", StringComparison.Ordinal));

        // No Authorization header is ever set on this client.
        Assert.Null(client.DefaultRequestHeaders.Authorization);
        var me = await client.GetAsync("/v1/auth/me");
        Assert.Equal(HttpStatusCode.OK, me.StatusCode);
        Assert.Equal("cookieonly@example.com", (await me.Content.ReadFromJsonAsync<JsonElement>()).GetProperty("email").GetString());
    }

    [Fact]
    public async Task Order_history_is_withheld_until_the_address_is_verified()
    {
        // Orders join to an account by email string, so an unverified account must see nothing —
        // otherwise registering with someone else's address would hand over their purchases. The
        // endpoint answers 200 with the flag rather than 403, because the page has to tell the
        // difference between "verify your address" and "your session expired".
        var client = _factory.CreateClient();
        await client.PostAsJsonAsync("/v1/auth/register", Registration("orderhist", "orderhist@example.com"));
        var (userId, token) = await ConfirmationTokenAsync("orderhist@example.com");

        // Sign in is impossible before verification, so reach the endpoint the only way an
        // unverified session could exist: verify, log in, then take the flag away again.
        await client.PostAsJsonAsync("/v1/auth/verify-email", new { user_id = userId, token });
        await client.PostAsJsonAsync("/v1/auth/login", new { username = "orderhist", password = "correct-horse-8" });

        var verified = await client.GetFromJsonAsync<JsonElement>("/v1/auth/me/orders");
        Assert.True(verified.GetProperty("email_confirmed").GetBoolean());

        using (var scope = _factory.Services.CreateScope())
        {
            var users = scope.ServiceProvider.GetRequiredService<UserManager<StoreUser>>();
            var user = await users.FindByEmailAsync("orderhist@example.com");
            user!.EmailConfirmed = false;
            await users.UpdateAsync(user);
        }

        // Same still-valid session. The read must re-check the flag, not trust the token.
        var revoked = await client.GetFromJsonAsync<JsonElement>("/v1/auth/me/orders");
        Assert.False(revoked.GetProperty("email_confirmed").GetBoolean());
        Assert.Empty(revoked.GetProperty("orders").EnumerateArray());
    }

    [Fact]
    public async Task Logging_out_invalidates_the_access_token_immediately()
    {
        var client = _factory.CreateClient();
        await client.PostAsJsonAsync("/v1/auth/register", Registration("logsout", "logsout@example.com"));
        var (userId, token) = await ConfirmationTokenAsync("logsout@example.com");
        await client.PostAsJsonAsync("/v1/auth/verify-email", new { user_id = userId, token });

        var login = await client.PostAsJsonAsync("/v1/auth/login", new { username = "logsout", password = "correct-horse-8" });
        var jwt = (await login.Content.ReadFromJsonAsync<JsonElement>()).GetProperty("token").GetString();
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", jwt);

        Assert.Equal(HttpStatusCode.OK, (await client.GetAsync("/v1/auth/me")).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await client.PostAsync("/v1/auth/logout", content: null)).StatusCode);

        // Same token: still signed correctly and still inside its lifetime. It must be refused
        // anyway, because logout added its JTI to the deny list the JwtBearer OnTokenValidated
        // hook checks. Without that hook, "log out" would be a lie for the rest of the expiry.
        Assert.Equal(HttpStatusCode.Unauthorized, (await client.GetAsync("/v1/auth/me")).StatusCode);
    }
}
