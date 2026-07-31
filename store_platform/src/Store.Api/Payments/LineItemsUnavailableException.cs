namespace Store.Api.Payments;

/// <summary>
/// Thrown when a multi-pack checkout session's per-line amounts cannot be established.
/// </summary>
/// <remarks>
/// This is deliberately fatal to the webhook rather than something to degrade past. Without
/// per-line amounts the only alternatives are to grant on a guessed split — which defeats
/// FulfilmentService's price fence — or to grant nothing and silently strand a paying buyer.
/// Failing the webhook picks a third option: the money is already captured, the event is
/// replayable, Stripe retries it, and the error is loud.
/// </remarks>
public sealed class LineItemsUnavailableException(string message, Exception? inner = null)
    : Exception(message, inner);
