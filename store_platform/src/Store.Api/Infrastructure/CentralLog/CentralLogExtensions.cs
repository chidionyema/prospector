using Microsoft.Extensions.DependencyInjection.Extensions;

namespace Store.Api.Infrastructure.CentralLog;

public static class CentralLogExtensions
{
    /// <summary>
    /// Wires the central log producer. Safe to call unconditionally: with no ingest URL or no
    /// <c>STORE_INTERNAL_API_KEY</c> the provider reports <c>IsEnabled == false</c> for every
    /// category and the shipper returns immediately, so a developer run costs one object.
    /// </summary>
    public static IServiceCollection AddCentralLog(this IServiceCollection services, IConfiguration configuration)
    {
        var options = CentralLogOptions.FromConfiguration(configuration);
        services.TryAddSingleton(options);
        services.TryAddSingleton(sp => new CentralLogBuffer(sp.GetRequiredService<CentralLogOptions>()));
        services.AddHttpContextAccessor();
        services.AddSingleton<ILoggerProvider, CentralLogProvider>();
        services.AddHostedService<CentralLogShipper>();
        return services;
    }
}
