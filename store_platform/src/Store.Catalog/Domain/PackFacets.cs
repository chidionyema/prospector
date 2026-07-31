namespace Store.Catalog.Domain;

/// <summary>
/// The closed facet vocabulary, defined once for the whole stack.
///
/// These are the values the buyer routes on: what they already have (advantage), who they
/// want to sell to (payer), how much of delivery a machine can do (effort), how many hours
/// they have (commitment), how the thing makes money (mechanism), and the industry it sits
/// in (sector). The engine emits them from a verified dossier; the API validates against
/// this list at the boundary; the browser only ever renders what it was given.
///
/// Two rules this type exists to enforce:
///
/// 1. No facet is ever inferred from pack text. The previous storefront guessed sector with
///    a regex over title+one-liner and told buyers a metal-fabrication quoting engine was a
///    gardening business. On a brand whose whole position is "every claim sourced", a filter
///    that lies is worse than no filter.
/// 2. Absent means absent. An untagged pack is null here and shows only under "All" — never
///    under a specific value, never defaulted, never "probably".
/// </summary>
public static class PackFacets
{
    /// <summary>What the buyer already has. Multi-valued (0-3) — the primary router input.</summary>
    public static readonly IReadOnlySet<string> Advantage =
        new HashSet<string>(StringComparer.Ordinal) { "code", "nocode", "sales", "ops", "audience" };

    /// <summary>Who signs the cheque. Buyers self-select hard on this.</summary>
    public static readonly IReadOnlySet<string> Payer =
        new HashSet<string>(StringComparer.Ordinal) { "b2b", "b2c", "b2g" };

    /// <summary>
    /// How much of delivery is machine-doable. Replaces the legacy low|medium|high mush,
    /// which was never defined to mean this and must not be string-mapped into it.
    /// </summary>
    public static readonly IReadOnlySet<string> Effort =
        new HashSet<string>(StringComparer.Ordinal) { "automatable", "part_automatable", "hands_on" };

    /// <summary>
    /// Hours needed to run it. Deliberately separate from <see cref="Effort"/>: a hands-on
    /// service can be evenings-only, and an automatable tool can still be a full-time sales
    /// grind. Conflating the two is what makes a time question dishonest.
    /// </summary>
    public static readonly IReadOnlySet<string> Commitment =
        new HashSet<string>(StringComparer.Ordinal) { "evenings", "part_time", "full_time" };

    /// <summary>
    /// The structural form — how it makes money. This is the real "more like this" axis:
    /// a buyer who liked B2B fee recovery but not vets wants the same mechanism in a
    /// different sector, which sector-similarity would never give them.
    /// </summary>
    public static readonly IReadOnlySet<string> Mechanism =
        new HashSet<string>(StringComparer.Ordinal)
        {
            "productized_service", "vertical_tool", "transaction_broker", "risk_financing",
            "physical_ops", "audience_media", "picks_and_shovels", "data_intelligence",
        };

    /// <summary>Display and exclusion only ("anything but vets") — never the primary filter.</summary>
    public static readonly IReadOnlySet<string> Sector =
        new HashSet<string>(StringComparer.Ordinal)
        {
            "licensing_admin", "employment_pay", "housing_rental", "care_benefits",
            "trades_construction", "pets_animals", "creative_rights", "property_probate",
            "energy_planning", "retail_inventory", "professional_services", "other",
        };

    /// <summary>
    /// Validate one single-valued facet. Null and empty are always valid — an absent facet is
    /// a legitimate state, not an error, and is the whole point of the null rule.
    /// Returns false and sets <paramref name="error"/> when the value is outside the vocabulary.
    /// </summary>
    public static bool TryValidate(string field, string? value, IReadOnlySet<string> allowed, out string? error)
    {
        error = null;
        if (string.IsNullOrWhiteSpace(value)) return true;
        // Explicit ordinal comparer (MA0002). Facet codes are machine tokens, never
        // user text, so ordinal is the correct comparison — a culture-aware one could
        // equate distinct codes under some locales.
        if (allowed.Contains(value, StringComparer.Ordinal)) return true;

        error = $"{field}: '{value}' is not a recognised value. Allowed: {string.Join(", ", allowed.OrderBy(v => v, StringComparer.Ordinal))}.";
        return false;
    }

    /// <summary>
    /// Validate a whole facet payload in one call — the single entry point both
    /// <c>POST /internal/catalog</c> and <c>PATCH /internal/catalog/{id}/facets</c> use, so
    /// the two write paths cannot drift apart in what they accept. Returns false on the first
    /// offending field, with an error naming the field and its allowed set.
    ///
    /// Callers must run this <b>before</b> touching the database: a rejected payload must
    /// write nothing at all, or a publish carrying one bad value would half-tag a pack and the
    /// filter would start making a claim the engine never made.
    /// </summary>
    public static bool TryValidateAll(
        string? sector,
        string? payer,
        string? effort,
        string? commitment,
        string? mechanism,
        IEnumerable<string>? advantages,
        out string? error)
    {
        foreach (var (field, value, allowed) in new (string, string?, IReadOnlySet<string>)[]
                 {
                     ("sector", sector, Sector),
                     ("payer", payer, Payer),
                     ("effort", effort, Effort),
                     ("commitment", commitment, Commitment),
                     ("mechanism", mechanism, Mechanism),
                 })
        {
            if (!TryValidate(field, value, allowed, out error)) return false;
        }

        return TryValidateAdvantages(advantages, out error);
    }

    /// <summary>
    /// Validate the multi-valued advantage list. Null is valid; an empty array is valid;
    /// any unknown member fails the whole request so a partial write can never happen.
    /// </summary>
    public static bool TryValidateAdvantages(IEnumerable<string>? values, out string? error)
    {
        error = null;
        if (values is null) return true;

        foreach (var v in values)
        {
            if (!TryValidate("advantages", v, Advantage, out error)) return false;
        }
        return true;
    }
}
