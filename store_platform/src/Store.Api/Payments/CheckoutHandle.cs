namespace Store.Api.Payments;

public sealed record CheckoutHandle(string Url, string? ClientSecret);
