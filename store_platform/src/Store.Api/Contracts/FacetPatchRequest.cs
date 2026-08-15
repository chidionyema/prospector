namespace Store.Api.Contracts;

/// <summary>
/// Contract for PATCH /internal/catalog/{id}/facets — the endpoint the facet backfill uses to
/// tag packs that were published before the facet vocabulary existed.
///
/// It is separate from <see cref="PublishRequest"/> on purpose. A backfill must be able to tag
/// a pack without re-sending its title, price, or content hash; making it go through publish
/// would mean a tagging job could rewrite the money-bearing fields of a live listing.
///
/// PATCH semantics, and the one thing to know about them:
/// <list type="bullet">
/// <item>a field left out (null) is <b>left unchanged</b>;</item>
/// <item>a field sent as the empty string is <b>cleared back to untagged</b> — the explicit
/// escape hatch for undoing a wrong tag, because with null already meaning "no change" there
/// would otherwise be no way to say "this tag was wrong, remove it";</item>
/// <item><see cref="Advantages"/> is a whole-list replace, and an empty array clears it.</item>
/// </list>
/// Unknown values are rejected with 400 before anything is written, exactly as on publish.
/// </summary>
/// <remarks>
/// <see cref="Market"/> is not one of <c>PackFacets</c>' closed vocabularies, but it belongs on
/// this endpoint for the same reason they do: it is a browse/disclosure tag that the engine can
/// get wrong or fail to record, and until now the ONLY way to correct it was
/// <c>POST /internal/catalog</c> — the upsert that assigns provider ids unconditionally, i.e.
/// the money rail. Three live packs (2026-08-14) carried a null market while their dossiers
/// recorded "uk", so the storefront grouped them under "Built for UK rules" on the strength of
/// a default rather than a fact, and no safe door existed to fix it.
/// </remarks>
public record FacetPatchRequest(
    string? Sector = null,
    string? Payer = null,
    string? Effort = null,
    string? Commitment = null,
    string? Mechanism = null,
    string[]? Advantages = null,
    string? Market = null
);
