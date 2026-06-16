using Store.Api.Services;

namespace Store.Tests.Services;

public sealed class TokenGeneratorTests
{
    [Fact]
    public void NewToken_IsUrlSafe()
    {
        var token = new TokenGenerator().NewToken();

        Assert.False(string.IsNullOrEmpty(token));
        Assert.DoesNotContain('+', token);
        Assert.DoesNotContain('/', token);
        Assert.DoesNotContain('=', token);
    }

    [Fact]
    public void NewToken_IsUniquePerCall()
    {
        var gen = new TokenGenerator();
        var tokens = new HashSet<string>(StringComparer.Ordinal);

        for (var i = 0; i < 100; i++)
        {
            Assert.True(tokens.Add(gen.NewToken()), "Token generator produced a collision.");
        }
    }
}
