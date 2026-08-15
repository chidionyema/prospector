namespace Store.Api.Services;

/// <summary>
/// What one pass of <see cref="DeliveryDrain"/> did. Its own file alongside
/// <c>FulfilmentOutcome</c> and <c>RevocationOutcome</c>, which is both the convention here and
/// what MA0048 requires.
/// </summary>
/// <param name="Sent">Links that went out on this pass.</param>
/// <param name="Failed">Attempts that failed and were counted towards the retry ceiling.</param>
/// <param name="Skipped">
/// Rows left completely untouched because delivery is unconfigured -- deliberately NOT counted as
/// failures, so a missing mail token cannot retire real obligations.
/// </param>
public sealed record DeliveryDrainResult(int Sent, int Failed, int Skipped);
