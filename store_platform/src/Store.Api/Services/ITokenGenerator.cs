namespace Store.Api.Services;

/// <summary>Issues opaque, non-enumerable credentials (grant tokens for magic links).</summary>
public interface ITokenGenerator
{
    string NewToken();
}
