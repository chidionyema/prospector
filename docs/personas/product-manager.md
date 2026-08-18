# The platform for the product manager

What the buyer receives, what shape the product actually is, and where the honest gaps are.

## The product in one paragraph

Somebody wants to start a business and does not know which idea is worth their year. This platform
generates candidate ideas, puts each through seven evidence checks against sources it actually
fetched, kills most of them with cited reasons, and sells a research pack on the survivors. The thing
being sold is not the idea. **It is the evidence, and the fact that most ideas died.**

## What a buyer gets

A pack, rendered deterministically from the verdict data. `docs/PACK_NARRATIVE_PROGRAM.md` holds the
reading order — read it before changing anything a buyer sees.

The properties that make it defensible as a product:

- **Every claim cites a source.** Unsourced numbers do not ship; they ship marked `unverifiable`.
- **Citations are archived at vet time**, so the claim stays checkable after the source page dies.
- **A KILL is a first-class artefact.** A dossier is rendered for every kill, not only for passes. The
  kill log is the receipt that the filter is real.
- **The same six checks apply to any business, any sector, any scale**, by the same bar. That
  universality is the brand promise.

## Segmentation

The catalogue is deliberately mixed-ambition. Four lanes run simultaneously —
`side_hustle`, `smb`, `growth`, `venture` (`config.yaml:588`) — and each candidate is auto-classified
into its natural tier and then judged against **that tier's** bar. A buyer looking for a £30 side
hustle and a buyer wanting to raise browse the same catalogue, and each item is graded by its own
class.

Historical PASS rate by lane across 221 tier-tagged dossiers: smb 11.8% (6/51), growth 4.9% (2/41),
side_hustle 4.3% (4/94), venture 0.0% (0/35). Small denominators — direction, not precision. Lane
quotas were rebalanced on 2026-08-01 from those numbers rather than from a guess about which tier
sounds most ambitious.

## The purchase path

Seven steps, and the whole of it is the money rail:

1. Buyer lands on `mumchimp.com`.
2. The storefront reads `api.mumchimp.com/catalog`.
3. They open a pack page.
4. `/checkout` or `/packs/{id}/checkout` creates a Stripe session.
5. Stripe calls `/webhooks/{provider}`.
6. An entitlement is written. **Exactly one outbox row per entitlement** is the idempotency guard.
7. `/orders/{token}` and `/download/{token}` deliver.

There is no account. The model is deliberately accountless — a token in a link, not a login. That is
a product decision with real support consequences; see [support.md](support.md).

## The two loops, and why they never merge

**Sales metrics tune what to offer. Truth metrics veto what may ship. Demand never overrides truth.**

Concretely: if a category sells well, that may change what the engine generates. It may never change
what passes the gates. A PASS requires clearing every hard gate and surviving adversarial review, and
nothing on the demand side can grant one.

This is the constraint most likely to be argued with, and it is the one that keeps the product from
becoming a content mill.

## Where the product is weakest today

Stated plainly rather than diplomatically.

1. **Discovery.** Facet coverage is the bottleneck. A catalogue nobody can navigate sells like a
   catalogue nobody has.
2. **Supply, not delivery.** Geo delivery works; supply does not. The constraint is how many packs
   clear the gates, not how many can be shipped.
3. **Ideas that clear the gates and then score too low.** They survive every check and die at
   `min_composite_to_pass: 2.5`. That is a scoring calibration question with direct revenue effect,
   and `docs/GENERATION_QUALITY_PROGRAM.md` is where it is tracked. The founder's steer is explicit:
   **improve generation quality, not the kill rate.**
4. **Backlog was never blocked on model cost.** Worth knowing, because it is the intuitive
   explanation and it is wrong.

## Things that are deliberately off

Do not propose these as new ideas; they are decisions.

- `comparables.rung_adjust_enabled` — retrieved price comparables do **not** move prices. Evidence and
  action are separate switches, or the catalogue re-prices itself the day a feature merges.
- `prescreen_prefilter` — the embedding-based prefilter is wired off.
- The hard subscription spend cap — arming it freezes the backlog, which defers cost rather than
  saving it.
- Streamlit control centre — deleted permanently.

## What is not built

No subscriptions (`docs/SUBSCRIPTION_PROGRAM.md` is a spec, not a shipped feature). No accounts. No
reviews, no ratings, no recommendations. No email beyond delivery. No analytics product surface.

## What to read next

- [buyer.md](buyer.md) — the same product from the other side of the counter.
- [analyst.md](analyst.md) — the funnel numbers behind every claim above.
- `docs/COMMERCIAL_READINESS_PROGRAM.md`, `docs/GENERATION_QUALITY_PROGRAM.md`.
