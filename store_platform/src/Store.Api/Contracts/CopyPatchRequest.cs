namespace Store.Api.Contracts;

/// <summary>
/// Contract for PATCH /internal/catalog/{id}/copy — the endpoint the listing-copy backfill uses
/// to replace the deterministic floor copy on packs that were published while their dossier had
/// no listing_page artifact.
///
/// It is separate from <see cref="PublishRequest"/> for a sharper reason than the facets one.
/// POST /internal/catalog is an upsert, and on the update path it assigns ProviderProductId and
/// ProviderPriceId unconditionally (from <c>request.X ?? request.PaddleX</c>) while never
/// reassigning PricePence at all — that only happens on INSERT. A copy job routed through
/// publish therefore has two ways to break a live pack, both silent:
/// <list type="bullet">
/// <item>omit the provider ids and they are set to <b>null</b>, which breaks the webhook's
/// product lookup in FulfilmentService (<c>p.ProviderProductId == item.ProductId</c>) — the
/// buyer pays and delivery never resolves;</item>
/// <item>send freshly minted ones (what EngineBridge.publish_pass does on every call) and the
/// buy button points at a price minted at today's ladder number while PricePence and
/// MinBillablePence still hold the old one — the buyer is charged the new amount and the
/// fulfilment fence refuses to deliver, with nothing in the catalogue row looking changed.</item>
/// </list>
/// ProviderProductId is also readable from no GET projection, so a copy job that went through
/// publish could not even restore what it was about to overwrite.
///
/// This endpoint reaches none of those fields. It can write copy and nothing else.
///
/// PATCH semantics are the same as <see cref="FacetPatchRequest"/>:
/// <list type="bullet">
/// <item>a field left out (null) is <b>left unchanged</b>;</item>
/// <item>a field sent as the empty string is <b>cleared</b>, so wrong copy can be withdrawn —
/// the null rule is only trustworthy if "remove this" is reachable;</item>
/// <item><see cref="WhatYouGet"/> and <see cref="SampleExtract"/> are whole-list replaces, and
/// an empty array clears them.</item>
/// </list>
/// Nothing here is validated against a vocabulary: every field is prose written for a buyer.
/// Length is enforced by the engine, which discards an over-length line rather than truncating
/// it, exactly as on publish — a server-side limit added here would 400 on copy that publish
/// itself would have accepted.
/// </summary>
public record CopyPatchRequest(
    string? CardLine = null,
    string? Headline = null,
    string? Subhead = null,
    string? ProofPoint = null,
    string? WhoPays = null,
    string? EffortTag = null,
    string? TimeToFirstRevenue = null,
    string[]? WhatYouGet = null,
    string[]? SampleExtract = null
);
