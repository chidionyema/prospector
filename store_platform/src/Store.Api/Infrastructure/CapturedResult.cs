namespace Store.Api.Infrastructure;

/// <summary>An <see cref="IResult"/> that writes a previously captured (or replayed) response.</summary>
internal sealed class CapturedResult(int statusCode, string? contentType, byte[] body) : IResult
{
    public async Task ExecuteAsync(HttpContext httpContext)
    {
        httpContext.Response.StatusCode = statusCode;
        if (!string.IsNullOrEmpty(contentType))
            httpContext.Response.ContentType = contentType;
        if (body.Length > 0)
            await httpContext.Response.Body.WriteAsync(body, httpContext.RequestAborted).ConfigureAwait(false);
    }
}
