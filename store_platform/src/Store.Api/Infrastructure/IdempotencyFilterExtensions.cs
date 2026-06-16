namespace Store.Api.Infrastructure;

public static class IdempotencyFilterExtensions
{
    /// <summary>
    /// Guards a mutating endpoint with request-level idempotency keyed on the
    /// <c>Idempotency-Key</c> header. <paramref name="required"/> (the default) rejects
    /// requests that omit the header with 400 — appropriate for money/state-changing calls.
    /// </summary>
    public static RouteHandlerBuilder WithIdempotency(this RouteHandlerBuilder builder, bool required = true)
        => builder.AddEndpointFilter(async (ctx, next) =>
            await new IdempotencyFilter(required).InvokeAsync(ctx, next).ConfigureAwait(false));
}
