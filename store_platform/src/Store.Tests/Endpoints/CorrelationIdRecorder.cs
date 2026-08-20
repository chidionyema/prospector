namespace Store.Tests.Endpoints;

/// <summary>What one real request through the API left behind, for the one-id test to compare.</summary>
internal sealed class CorrelationIdRecorder
{
    /// <summary>The id Crux.Observability's middleware stored, read by its own key.</summary>
    public string? PackageValue { get; set; }

    /// <summary>What <c>HttpContext.GetCorrelationId()</c> answered for the same request.</summary>
    public string? OurValue { get; set; }

    /// <summary>The framework's trace id, the value we fall back to when nothing better exists.</summary>
    public string? TraceIdentifier { get; set; }
}
