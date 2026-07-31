using Store.Api.Contracts;
using Store.Catalog.Domain;

namespace Store.Tests.Domain;

/// <summary>
/// The facet contract is the spine of discovery: engine → publish API → database → read API →
/// browser, one closed vocabulary, never inferred in the browser. These tests pin the boundary
/// that keeps it honest.
///
/// What they cover, stated precisely so the coverage is not overclaimed: they exercise
/// <see cref="PackFacets.TryValidateAll"/>, which is the single validator both write paths call
/// (<c>POST /internal/catalog</c> and <c>PATCH /internal/catalog/{id}/facets</c>) before they
/// touch the database. They do not spin an HTTP host, so they prove the rule, not the wiring —
/// the wiring is one call site each, visible in Program.cs.
/// </summary>
public class PackFacetTests
{
    private static readonly string[] OneGoodOneBadAdvantage = ["code", "telepathy"];

    // AC-2 — a publish carrying an unknown facet value is rejected, and the rejection names
    // both the offending field and the allowed set so the engine operator can fix it without
    // reading the source.
    [Fact]
    public void Publish_RejectsUnknownFacetValue()
    {
        var request = new PublishRequest("p1", "T", "O", "d1", Effort: "high");

        var ok = PackFacets.TryValidateAll(
            request.Sector, request.Payer, request.Effort,
            request.Commitment, request.Mechanism, request.Advantages, out var error);

        Assert.False(ok);
        Assert.NotNull(error);
        Assert.Contains("effort", error, StringComparison.Ordinal);
        Assert.Contains("high", error, StringComparison.Ordinal);
        // The allowed set is quoted back in full.
        Assert.Contains("automatable", error, StringComparison.Ordinal);
        Assert.Contains("part_automatable", error, StringComparison.Ordinal);
        Assert.Contains("hands_on", error, StringComparison.Ordinal);
    }

    // The specific trap from spec 2.3: the legacy low|medium|high effortTag vocabulary must not
    // be quietly accepted into the new enum. "high" was never defined to mean "hands_on", and a
    // string map would be a guess wearing the costume of data.
    [Theory]
    [InlineData("low")]
    [InlineData("medium")]
    [InlineData("high")]
    [InlineData("Highly automatable")]
    [InlineData("Hands on service")]
    public void Publish_RejectsLegacyEffortTagVocabulary(string legacyValue)
    {
        Assert.False(PackFacets.TryValidateAll(null, null, legacyValue, null, null, null, out _));
    }

    [Fact]
    public void Publish_RejectsUnknownAdvantage_WithoutPartialAcceptance()
    {
        // One bad member fails the whole list. A partial accept would leave a pack tagged with
        // an advantage the engine never justified.
        var ok = PackFacets.TryValidateAll(
            null, null, null, null, null, OneGoodOneBadAdvantage, out var error);

        Assert.False(ok);
        Assert.Contains("telepathy", error!, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("sector", "underwater_basketry")]
    [InlineData("payer", "b2x")]
    [InlineData("commitment", "weekends")]
    [InlineData("mechanism", "niche_distribution")]  // a real drifted value from the dossiers
    public void EveryFacet_RejectsValuesOutsideItsVocabulary(string field, string value)
    {
        // Only the named facet carries the bad value; every other one stays absent, so the
        // failure can only have come from the field under test.
        string? Only(string name) => string.Equals(field, name, StringComparison.Ordinal) ? value : null;

        var ok = PackFacets.TryValidateAll(
            sector: Only("sector"),
            payer: Only("payer"),
            effort: Only("effort"),
            commitment: Only("commitment"),
            mechanism: Only("mechanism"),
            advantages: null,
            out var error);

        Assert.False(ok);
        Assert.Contains(field, error!, StringComparison.Ordinal);
    }

    // AC-3 — a publish that omits every facet still succeeds. This is the null rule at the
    // boundary: absent is a legitimate state, not an error.
    [Fact]
    public void Publish_OmittingFacets_IsValid()
    {
        var request = new PublishRequest("p1", "T", "O", "d1");

        Assert.Null(request.Sector);
        Assert.Null(request.Payer);
        Assert.Null(request.Effort);
        Assert.Null(request.Commitment);
        Assert.Null(request.Mechanism);
        Assert.Null(request.Advantages);

        Assert.True(PackFacets.TryValidateAll(
            request.Sector, request.Payer, request.Effort,
            request.Commitment, request.Mechanism, request.Advantages, out var error));
        Assert.Null(error);
    }

    // The back-compat guarantee that makes the append-only rule real. PackMarketTests.cs:29-31
    // constructs exactly this and must keep compiling untouched; so must every existing caller
    // that predates the facet columns.
    [Fact]
    public void PublishRequest_PositionalParameters_StayAppendOnly()
    {
        var minimal = new PublishRequest("p1", "T", "O", "d1");
        Assert.Equal("p1", minimal.Id);
        Assert.Equal("d1", minimal.DossierRef);
        Assert.Null(minimal.Market);
    }

    [Fact]
    public void FacetPatch_OmittingEverything_IsValid()
    {
        var patch = new FacetPatchRequest();
        Assert.True(PackFacets.TryValidateAll(
            patch.Sector, patch.Payer, patch.Effort,
            patch.Commitment, patch.Mechanism, patch.Advantages, out _));
    }

    // The clear-a-tag escape hatch. The empty string means "untag" on PATCH, so the validator
    // must treat it as valid rather than as an unknown value — otherwise a wrong tag applied
    // by a backfill could never be withdrawn.
    [Fact]
    public void FacetPatch_EmptyStringIsValid_BecauseItMeansUntag()
    {
        Assert.True(PackFacets.TryValidateAll("", "", "", "", "", [], out _));
    }

    [Fact]
    public void Pack_FacetsDefaultToNull_SoPacksPublishedBeforeThisStoryStayValid()
    {
        var pack = new Pack { Id = "p1", Title = "T", OneLine = "O", DossierRef = "d1", PricePence = 4900 };

        Assert.Null(pack.Sector);
        Assert.Null(pack.Payer);
        Assert.Null(pack.Effort);
        Assert.Null(pack.Commitment);
        Assert.Null(pack.Mechanism);
        Assert.Null(pack.AdvantagesJson);
    }

    [Fact]
    public void EveryVocabulary_IsNonEmpty_AndMatchesTheSpec()
    {
        // Guards against a merge silently emptying a set, which would turn TryValidate into a
        // reject-everything gate and take the whole publish path down.
        Assert.Equal(5, PackFacets.Advantage.Count);
        Assert.Equal(3, PackFacets.Payer.Count);
        Assert.Equal(3, PackFacets.Effort.Count);
        Assert.Equal(3, PackFacets.Commitment.Count);
        Assert.Equal(8, PackFacets.Mechanism.Count);
        Assert.Equal(12, PackFacets.Sector.Count);
    }
}
