namespace Store.Api.Contracts;

/// <summary>
/// Repoint a pack's deliverable at a new content object, touching nothing else about it.
///
/// Content storage is content-addressed (packs/&lt;id&gt;/&lt;sha256-of-zip&gt;.zip), so any change to a
/// bundle — even an additive one like the in-zip HTML reader — lands at a NEW object key, and
/// the listing must be repointed or buyers keep receiving the old zip. Re-POSTing to
/// /internal/catalog for that would put a formatting backfill in a position to rewrite title,
/// price, provider ids and listing state (that endpoint assigns them unconditionally); this
/// door can only reach the content pointer. All three fields are required: a key without its
/// hash would break download integrity verification, and an unexplained repoint reads as a bug.
/// </summary>
public record ContentPatchRequest(string ContentKey, string ContentHash, string Reason);
