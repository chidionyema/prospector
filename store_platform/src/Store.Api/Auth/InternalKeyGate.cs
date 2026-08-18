using System.Security.Cryptography;
using System.Text;

namespace Store.Api.Auth;

/// <summary>
/// The fail-closed <c>X-Internal-Key</c> check that fences every <c>/internal/*</c> route.
///
/// The check itself is not new — <c>POST /internal/catalog</c> (Program.cs) and
/// <c>AnalyticsEndpoints.RejectUnlessInternal</c> each carry their own copy. This class exists
/// because <c>OpsEndpoints</c> would have been the third, and the ops routes read orders,
/// buyer emails and revenue. A key check that drifts between copies is the failure that opens
/// one of them.
///
/// Fail-closed means: no key configured on the server is a 503, never an open door.
/// </summary>
public static class InternalKeyGate
{
    /// <summary>
    /// Returns null when the caller is authorised, or the <see cref="IResult"/> to return.
    /// </summary>
    public static IResult? Reject(HttpRequest http, IConfiguration config)
    {
        var expectedKey = config["Store:InternalApiKey"]
            ?? Environment.GetEnvironmentVariable("STORE_INTERNAL_API_KEY");
        if (string.IsNullOrEmpty(expectedKey))
        {
            return Results.Problem(
                "Internal API key not configured",
                statusCode: StatusCodes.Status503ServiceUnavailable);
        }

        var providedKey = http.Headers["X-Internal-Key"].ToString();
        if (string.IsNullOrEmpty(providedKey) ||
            !CryptographicOperations.FixedTimeEquals(
                Encoding.UTF8.GetBytes(providedKey),
                Encoding.UTF8.GetBytes(expectedKey)))
        {
            return Results.Unauthorized();
        }

        return null;
    }
}
